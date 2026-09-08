#!/usr/bin/env python3
"""AppManager and BaseApp definitions for SO-101 robot application lifecycle.
Strictly compliant with reachy_mini.apps.app.ReachyMiniApp and reachy_mini.apps.manager.AppManager standards.
"""

import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Type, List, Callable
from robot_backend import RobotBackend, dispatch_audio_event


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
        self.start_callbacks: List[Callable[[str], None]] = []
        self.stop_callbacks: List[Callable[[str], None]] = []
        self.logger = logging.getLogger("so101.app_manager")

    def register_start_callback(self, callback: Callable[[str], None]) -> None:
        """Registers a callback hook invoked whenever an application starts."""
        self.start_callbacks.append(callback)

    def _notify_app_started(self, app_name: str) -> None:
        """Notifies all registered callbacks that an application has started."""
        for cb in list(self.start_callbacks):
            try:
                cb(app_name)
            except Exception as cb_err:
                self.logger.warning(f"Error in start callback for app '{app_name}': {cb_err}")

    def register_stop_callback(self, callback: Callable[[str], None]) -> None:
        """Registers a callback hook invoked whenever an application stops."""
        self.stop_callbacks.append(callback)

    def _notify_app_stopped(self, app_name: str) -> None:
        """Notifies all registered callbacks that an application has stopped."""
        for cb in list(self.stop_callbacks):
            try:
                cb(app_name)
            except Exception as cb_err:
                self.logger.warning(f"Error in stop callback for app '{app_name}': {cb_err}")

    def register_app(self, app_cls: Type[BaseApp]) -> None:
        """Registers a BaseApp subclass into the AppManager registry."""
        app_name = app_cls.metadata.name
        self.registry[app_name] = app_cls
        self.logger.info(f"Registered app '{app_name}' ({app_cls.metadata.title})")

    def discover_apps(self, apps_dir: Optional[str] = None) -> List[str]:
        """Dynamically scans apps/ directory, discovers self-contained app packages,
        and registers their BaseApp subclasses into the AppManager registry."""
        import importlib
        from pathlib import Path

        if apps_dir is None:
            possible = [
                Path(__file__).resolve().parent.parent / "apps",
                Path.home() / "so101" / "apps",
                Path("/home/carson/so101/apps"),
                Path("/home/user/so101/apps"),
                Path.cwd() / "apps",
            ]
            apps_path = None
            for p in possible:
                if p.is_dir():
                    apps_path = p
                    break
            if apps_path is None:
                self.logger.warning("No apps/ directory found for auto-discovery.")
                return []
        else:
            apps_path = Path(apps_dir).resolve()

        self.logger.info(f"Scanning for modular applications in: {apps_path}")
        discovered = []

        for item in sorted(apps_path.iterdir()):
            if not item.is_dir() or item.name.startswith((".", "_")):
                continue

            app_py = item / "app.py"
            config_json = item / "config.json"
            manifest_json = item / "manifest.json"

            if not app_py.exists():
                continue

            if not config_json.exists() and not manifest_json.exists():
                self.logger.warning(f"Skipping app folder '{item.name}': missing config.json or manifest.json")
                continue

            try:
                module_name = f"apps.{item.name}.app"
                mod = importlib.import_module(module_name)

                found = False
                for attr_name in dir(mod):
                    attr = getattr(mod, attr_name)
                    if isinstance(attr, type) and issubclass(attr, BaseApp) and attr is not BaseApp:
                        self.register_app(attr)
                        discovered.append(attr.metadata.name)
                        found = True

                if not found:
                    self.logger.warning(f"No BaseApp subclass found in {module_name}")
            except Exception as e:
                self.logger.error(f"Failed to auto-discover app from '{item.name}': {e}", exc_info=True)

        self.logger.info(f"Auto-discovery registered {len(discovered)} app(s): {discovered}")
        return discovered


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
            dispatch_audio_event(kind="incorrect")
            return False

        self.active_app = app_instance
        self.current_app_name = app_name
        app_instance.app_manager = self
        app_instance.error = ""

        # 3. Setup hook
        try:
            app_instance.setup(self.backend)
        except Exception as e:
            self.logger.error(f"App '{app_name}' setup failed: {e}")
            app_instance.error = str(e)
            dispatch_audio_event(kind="incorrect")
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
                dispatch_audio_event(kind="incorrect")
            finally:
                try:
                    app_instance.teardown(self.backend)
                except Exception as te:
                    self.logger.warning(f"App '{app_name}' teardown warning: {te}")
                with self.lock._lock:
                    if self.current_app_name == app_name:
                        self.active_app = None
                        self.current_app_name = None
                        if self.lock._owner == app_name:
                            self.lock._owner = None
                dispatch_audio_event(kind="app_exit_idle")
                self.logger.info(f"Application '{app_name}' loop exited.")
                self._notify_app_stopped(app_name)

        app_instance.thread = threading.Thread(target=_runner, daemon=True)
        app_instance.thread.start()
        self._notify_app_started(app_name)

        # Dispatch application startup audio cue strictly AFTER worker thread starts
        start_cue = str(app_instance.config["chimes"]["app_start"])
        dispatch_audio_event(kind=start_cue)
        return True

    def stop_app(self, app_name: str) -> None:
        """Reachy Mini 5-stage Shutdown Compliance Protocol:
        1. Signal stop_event
        2. Wait for worker loop exit (join timeout 3.0s)
        3. Execute app teardown hook
        4. Release RobotAppLock
        5. Reset active app state
        """
        if self.current_app_name == app_name and self.active_app:
            app_inst = self.active_app
            self.logger.info(f"Executing 5-stage graceful shutdown for app '{app_name}'...")

            # Stage 1: Signal stop_event
            app_inst.stop()

            # Stage 2: Join worker thread
            if app_inst.thread and app_inst.thread.is_alive() and app_inst.thread != threading.current_thread():
                app_inst.thread.join(timeout=3.0)
                if app_inst.thread.is_alive():
                    self.logger.warning(f"App '{app_name}' thread did not exit within 3.0s timeout.")

            # Stage 3: App teardown hook
            try:
                app_inst.teardown(self.backend)
            except Exception as te:
                self.logger.warning(f"App '{app_name}' teardown warning: {te}")

            # Stage 4: Release mutex lock
            self.lock.release(app_name)

            # Stage 5: Clear state
            self.active_app = None
            self.current_app_name = None
            self.logger.info(f"App '{app_name}' successfully stopped and lock released.")
            self._notify_app_stopped(app_name)

    def stop_current_app(self) -> None:
        """Stops the currently running application, if any."""
        if self.current_app_name:
            self.stop_app(self.current_app_name)

    def stop_all(self) -> None:
        """Stops whatever app is currently active with full thread joining and mutex release."""
        if self.current_app_name:
            self.stop_app(self.current_app_name)
        elif self.active_app:
            try:
                self.active_app.stop()
                if self.active_app.thread and self.active_app.thread.is_alive() and self.active_app.thread != threading.current_thread():
                    self.active_app.thread.join(timeout=2.0)
            except Exception as e:
                self.logger.warning(f"Error stopping lingering active_app: {e}")
            self.active_app = None
        if self.lock.owner is not None:
            self.lock.release(self.lock.owner)

    def get_status(self) -> Dict[str, Any]:
        """Returns structured AppManager status for REST API inspection."""
        return {
            "current_app": self.current_app_name,
            "lock_owner": self.lock.owner,
            "active_app_error": self.active_app.error if self.active_app else "",
            "registered_apps": list(self.registry.keys()),
        }
