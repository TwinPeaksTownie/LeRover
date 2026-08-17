#!/usr/bin/env python3
"""AppManager and BaseApp definitions for SO-101 robot application lifecycle.
Strictly compliant with reachy_mini.apps.app.ReachyMiniApp and reachy_mini.apps.manager.AppManager standards.
"""

import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Type, List
from robot_backend import RobotBackend, SERIAL_LOCK


@dataclass
class AppMetadata:
    """Standardized metadata schema matching Reachy Mini app requirements."""
    name: str = "base_app"
    title: str = "Base Application"
    description: str = "SO-101 Base Application"
    version: str = "1.0.0"
    tags: List[str] = field(default_factory=lambda: ["so101"])
    icon: str = "🤖"


class BaseApp(ABC):
    """Base class for all SO-101 robot applications, matching ReachyMiniApp."""
    metadata: AppMetadata = AppMetadata()

    def __init__(self, running_on_pi: bool = True) -> None:
        self.stop_event = threading.Event()
        self.name: str = self.metadata.name
        self.logger = logging.getLogger(f"so101.app.{self.name}")
        self.error: str = ""
        self.thread: Optional[threading.Thread] = None

    def setup(self, backend: RobotBackend) -> None:
        """Optional pre-run setup hook."""
        pass

    @abstractmethod
    def run(self, backend: RobotBackend, stop_event: threading.Event) -> None:
        """Main execution logic of the app. Must monitor stop_event.is_set()."""
        pass

    def teardown(self, backend: RobotBackend) -> None:
        """Optional post-run cleanup hook."""
        pass

    def stop(self) -> None:
        """Gracefully signals the application loop to stop."""
        self.logger.info(f"Stopping application '{self.name}'...")
        self.stop_event.set()


class RobotAppLock:
    """Single-writer mutex protecting motor bus access across apps and Web APIs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._owner: Optional[str] = None

    def acquire(self, owner: str) -> bool:
        with self._lock:
            if self._owner is not None and self._owner != owner:
                raise RuntimeError(f"Robot lock held by {self._owner}")
            self._owner = owner
            return True

    def release(self, owner: str) -> None:
        with self._lock:
            if self._owner == owner:
                self._owner = None

    @property
    def owner(self) -> Optional[str]:
        with self._lock:
            return self._owner


class AppManager:
    """Manages application lifecycles, matching reachy_mini.apps.manager.AppManager architecture."""

    def __init__(self, backend: RobotBackend) -> None:
        self.backend = backend
        self.lock = RobotAppLock()
        self.active_app: Optional[BaseApp] = None
        self.current_app_name: Optional[str] = None
        self.registry: Dict[str, Type[BaseApp]] = {}
        self.logger = logging.getLogger("so101.app_manager")

    def register_app(self, app_cls: Type[BaseApp]) -> None:
        """Registers a BaseApp subclass into the AppManager registry."""
        app_name = app_cls.metadata.name
        self.registry[app_name] = app_cls
        self.logger.info(f"Registered app '{app_name}' ({app_cls.metadata.title})")

    def list_apps(self) -> List[Dict[str, Any]]:
        """Returns catalog of all registered applications and their metadata."""
        apps_info = []
        for name, cls in self.registry.items():
            meta = cls.metadata
            apps_info.append({
                "name": meta.name,
                "title": meta.title,
                "description": meta.description,
                "version": meta.version,
                "tags": meta.tags,
                "icon": meta.icon,
                "is_running": (self.current_app_name == meta.name),
            })
        return apps_info

    def get_app_info(self, app_name: str) -> Optional[Dict[str, Any]]:
        """Returns metadata for a specific application."""
        cls = self.registry.get(app_name)
        if not cls:
            return None
        meta = cls.metadata
        return {
            "name": meta.name,
            "title": meta.title,
            "description": meta.description,
            "version": meta.version,
            "tags": meta.tags,
            "icon": meta.icon,
            "is_running": (self.current_app_name == meta.name),
            "error": self.active_app.error if (self.active_app and self.current_app_name == app_name) else "",
        }

    def start_app_by_name(self, app_name: str, **kwargs) -> bool:
        """Instantiates an app from the registry by name and starts it."""
        if app_name not in self.registry:
            self.logger.error(f"Cannot start unknown app '{app_name}'")
            return False
        app_cls = self.registry[app_name]
        app_instance = app_cls(**kwargs)
        return self.start_app(app_instance)

    def start_app(self, app_instance: BaseApp) -> bool:
        """Reachy Mini Start Compliance Protocol:
        1. Stop active app if running
        2. Acquire RobotAppLock mutex
        3. Instantiate app with fresh stop_event
        4. Setup backend state
        5. Launch in crash-isolated background worker thread
        """
        app_name = app_instance.name

        # 1. Stop active app if running
        if self.current_app_name is not None:
            self.stop_app(self.current_app_name)

        # 2. Acquire Mutex Lock
        try:
            self.lock.acquire(app_name)
        except RuntimeError as e:
            self.logger.error(f"Failed to acquire lock for '{app_name}': {e}")
            return False

        self.active_app = app_instance
        self.current_app_name = app_name
        app_instance.error = ""

        # 3. Setup hook
        try:
            app_instance.setup(self.backend)
        except Exception as e:
            self.logger.error(f"App '{app_name}' setup failed: {e}")
            app_instance.error = str(e)
            self.lock.release(app_name)
            self.active_app = None
            self.current_app_name = None
            return False

        def _runner():
            try:
                self.logger.info(f"Starting application loop '{app_name}'...")
                app_instance.run(self.backend, app_instance.stop_event)
            except Exception as e:
                self.logger.error(f"Application '{app_name}' crashed: {e}", exc_info=True)
                app_instance.error = str(e)
            finally:
                try:
                    app_instance.teardown(self.backend)
                except Exception as te:
                    self.logger.warning(f"App '{app_name}' teardown warning: {te}")
                self.logger.info(f"Application '{app_name}' loop exited.")

        app_instance.thread = threading.Thread(target=_runner, daemon=True)
        app_instance.thread.start()
        return True

    def stop_app(self, app_name: str) -> None:
        """Reachy Mini 5-stage Shutdown Compliance Protocol:
        1. Signal stop_event
        2. Wait for worker loop exit (join timeout 3.0s)
        3. Force disarm / reset hardware state if needed
        4. Release RobotAppLock
        5. Reset active app state
        """
        if self.current_app_name == app_name and self.active_app:
            app_inst = self.active_app
            self.logger.info(f"Executing 5-stage graceful shutdown for app '{app_name}'...")

            # Stage 1: Signal stop_event
            app_inst.stop()

            # Stage 2: Join worker thread
            if app_inst.thread and app_inst.thread.is_alive():
                app_inst.thread.join(timeout=3.0)
                if app_inst.thread.is_alive():
                    self.logger.warning(f"App '{app_name}' thread did not exit within 3.0s timeout.")

            # Stage 3: Hardware safe reset / disarm
            try:
                if self.backend and self.backend.bus and hasattr(self.backend.bus, "disable_torque"):
                    with SERIAL_LOCK:
                        self.backend.bus.disable_torque(num_retry=1)
            except Exception as e:
                self.logger.warning(f"Hardware reset during '{app_name}' shutdown warning: {e}")

            # Stage 4: Release mutex lock
            self.lock.release(app_name)

            # Stage 5: Clear state
            self.active_app = None
            self.current_app_name = None
            self.logger.info(f"App '{app_name}' successfully stopped and lock released.")

    def stop_all(self) -> None:
        """Stops whatever app is currently active."""
        if self.current_app_name:
            self.stop_app(self.current_app_name)

    def get_status(self) -> Dict[str, Any]:
        """Returns structured AppManager status for REST API inspection."""
        return {
            "current_app": self.current_app_name,
            "lock_owner": self.lock.owner,
            "active_app_error": self.active_app.error if self.active_app else "",
            "registered_apps": list(self.registry.keys()),
        }
