class OpTreeError(Exception):
    """Base error for all optree failures."""


class CycleError(OpTreeError):
    """The node graph contains a dependency cycle."""


class BlenderError(OpTreeError):
    """A headless Blender execution failed."""
