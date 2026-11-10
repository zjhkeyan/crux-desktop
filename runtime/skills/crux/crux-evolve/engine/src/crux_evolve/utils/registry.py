"""Generic class registry for CruxEvolve plugin system.

Usage:
    # Define registry for a base class
    provider_registry = Registry("provider", BaseProvider)

    # Register with decorator (recommended)
    @provider_registry.register("openai")
    class OpenAIProvider(BaseProvider): ...

    # Or register manually
    provider_registry.register("custom", CustomProvider)

    # Create instance
    provider = provider_registry.create("openai", api_key="...")

    # Auto-discover from module
    provider_registry.discover("crux_evolve.provider")
"""

import contextlib
import importlib
from collections.abc import Callable
from typing import Any, ClassVar, TypeVar

T = TypeVar("T")
BaseT = TypeVar("BaseT", bound="Registrable")

__all__ = [
    "Registry",
    "Registrable",
    "T",
]


class Registry:
    """Generic plugin registry supporting dynamic module loading.

    This class provides a registry pattern for managing plugin classes.
    It supports decorator-based registration, manual registration,
    instance creation, and auto-discovery from modules.
    """

    def __init__(self, name: str, base_class: type[T]):
        """Initialize registry.

        Args:
            name: Name of this registry (for error messages)
            base_class: Base class that all registered classes must inherit from
        """
        self.name = name
        self.base_class = base_class
        self._registry: dict[str, type[T]] = {}

    def register(self, name: str, cls: type[T] | None = None) -> Callable | type[T]:
        """Register a class. Can be used as decorator.

        Args:
            name: Unique name for this class
            cls: Class to register (if None, returns decorator)

        Returns:
            Decorator function if cls is None, otherwise the class

        Raises:
            TypeError: If class doesn't inherit from base_class
        """

        def decorator(cls: type[T]) -> type[T]:
            if not issubclass(cls, self.base_class):
                raise TypeError(f"{cls.__name__} must inherit from {self.base_class.__name__}")
            self._registry[name] = cls
            # Also store name on class for reference
            cls._registry_name = name
            return cls

        if cls is None:
            return decorator
        return decorator(cls)

    def get(self, name: str) -> type[T]:
        """Get registered class by name.

        Args:
            name: Name of registered class

        Returns:
            Registered class

        Raises:
            KeyError: If name is not registered
        """
        if name not in self._registry:
            available = ", ".join(self._registry.keys())
            raise KeyError(f"Unknown {self.name}: '{name}'. " f"Available: {available}")
        return self._registry[name]

    def create(self, name: str, *args, **kwargs) -> T:
        """Create instance of registered class.

        Args:
            name: Name of registered class
            *args: Positional arguments for constructor
            **kwargs: Keyword arguments for constructor

        Returns:
            Instance of registered class
        """
        cls = self.get(name)
        return cls(*args, **kwargs)

    def list(self) -> list[str]:
        """List all registered names.

        Returns:
            List of registered class names
        """
        return list(self._registry.keys())

    def discover(self, module_path: str) -> int:
        """Auto-discover and register classes from module.

        Imports all submodules and any classes decorated with @register.
        Returns count of discovered registrations.

        Args:
            module_path: Python module path (e.g., 'crux_evolve.provider')

        Returns:
            Number of newly discovered registrations
        """
        import pkgutil

        module = importlib.import_module(module_path)

        # Import all submodules to trigger decorators
        count_before = len(self._registry)

        for _, name, _is_pkg in pkgutil.iter_modules(module.__path__, module.__name__ + "."):
            with contextlib.suppress(ImportError):
                importlib.import_module(name)

        return len(self._registry) - count_before

    def unregister(self, name: str) -> None:
        """Remove a registration.

        Args:
            name: Name of registered class to remove
        """
        if name in self._registry:
            del self._registry[name]


class Registrable:
    """Base class for registrable components.

    Inherit from this class to make your base class automatically support
    registration without needing to create a separate Registry instance.

    Usage:
        # Define your base class
        class BaseProvider(Registrable):
            pass

        # Register subclass
        @BaseProvider.register("openai")
        class OpenAIProvider(BaseProvider):
            pass

        # Create instance
        provider = BaseProvider.create("openai", api_key="...")
    """

    _registry: ClassVar[Registry | None] = None
    _registry_name: ClassVar[str]

    @classmethod
    def __init_subclass__(cls, registry_name: str | None = None, **kwargs: Any) -> None:
        """Initialize registry for the base class."""
        super().__init_subclass__(**kwargs)
        # Only create registry for the direct base class, not for subclasses
        if Registrable in cls.__bases__:
            registry_name = registry_name or cls.__name__.lower()
            if registry_name.startswith("base"):
                registry_name = registry_name[4:]
            cls._registry = Registry(registry_name, cls)

    @classmethod
    def register(
        cls, name: str, component_cls: type[BaseT] | None = None
    ) -> Callable | type[BaseT]:
        """Register a component class. Can be used as decorator.

        Args:
            name: Unique name for this component
            component_cls: Class to register (if None, returns decorator)

        Returns:
            Decorator function if component_cls is None, otherwise the class
        """
        if cls._registry is None:
            raise RuntimeError(
                f"Registry not initialized for {cls.__name__}. "
                "Only direct subclasses of Registrable can be used as base classes."
            )
        return cls._registry.register(name, component_cls)

    @classmethod
    def get(cls, name: str) -> type[BaseT]:
        """Get registered class by name."""
        if cls._registry is None:
            raise RuntimeError(
                f"Registry not initialized for {cls.__name__}. "
                "Only direct subclasses of Registrable can be used as base classes."
            )
        return cls._registry.get(name)

    @classmethod
    def create(cls, name: str, *args: Any, **kwargs: Any) -> BaseT:
        """Create instance of registered class."""
        if cls._registry is None:
            raise RuntimeError(
                f"Registry not initialized for {cls.__name__}. "
                "Only direct subclasses of Registrable can be used as base classes."
            )
        return cls._registry.create(name, *args, **kwargs)

    @classmethod
    def list(cls) -> list[str]:
        """List all registered component names."""
        if cls._registry is None:
            raise RuntimeError(
                f"Registry not initialized for {cls.__name__}. "
                "Only direct subclasses of Registrable can be used as base classes."
            )
        return cls._registry.list()

    @classmethod
    def discover(cls, module_path: str) -> int:
        """Auto-discover and register components from module."""
        if cls._registry is None:
            raise RuntimeError(
                f"Registry not initialized for {cls.__name__}. "
                "Only direct subclasses of Registrable can be used as base classes."
            )
        return cls._registry.discover(module_path)

    @classmethod
    def unregister(cls, name: str) -> None:
        """Remove a registration."""
        if cls._registry is None:
            raise RuntimeError(
                f"Registry not initialized for {cls.__name__}. "
                "Only direct subclasses of Registrable can be used as base classes."
            )
        cls._registry.unregister(name)
