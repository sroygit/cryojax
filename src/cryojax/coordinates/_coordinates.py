"""
Coordinate functionality in cryojax.
"""

from jaxtyping import ArrayLike, Array, PyTree, Float
from typing import Optional, Any
from typing_extensions import Self
from equinox import AbstractVar

import equinox as eqx
import jax.tree_util as jtu
import jax.numpy as jnp

from ..typing import (
    Image,
    CloudCoords3D,
    CloudCoords2D,
    ImageCoords,
    VolumeCoords,
    VolumeSliceCoords,
)


#
# Filter functions
#
def is_not_coordinates(element: Any) -> bool:
    """Returns ``False`` if ``element`` is ``AbstractCoordinates``."""
    if isinstance(element, AbstractCoordinates):
        return False
    else:
        return eqx.is_array(element)


#
# Common filter specs
#
def get_not_coordinate_filter_spec(pytree: PyTree) -> PyTree[bool]:
    """Filter spec that is ``True`` for all arrays that are not ``Coordinates``."""
    return jtu.tree_map(
        is_not_coordinates,
        pytree,
        is_leaf=lambda x: isinstance(x, AbstractCoordinates),
    )


class AbstractCoordinates(eqx.Module, strict=True):
    """
    A base class that wraps a coordinate array.
    """

    array: AbstractVar[Any]

    def get(self):
        """Get the coordinates."""
        return self.array

    def __mul__(self, arr: ArrayLike) -> Self:
        return eqx.tree_at(lambda x: x.array, self, self.array * jnp.asarray(arr))

    def __rmul__(self, arr: ArrayLike) -> Self:
        return eqx.tree_at(lambda x: x.array, self, jnp.asarray(arr) * self.array)

    def __truediv__(self, arr: ArrayLike) -> Self:
        return eqx.tree_at(lambda x: x.array, self, self.array / jnp.asarray(arr))

    def __rtruediv__(self, arr: ArrayLike) -> Self:
        return eqx.tree_at(lambda x: x.array, self, jnp.asarray(arr) / self.array)


class CoordinateList(AbstractCoordinates, strict=True):
    """
    A Pytree that wraps a coordinate list.
    """

    array: CloudCoords3D | CloudCoords2D = eqx.field(converter=jnp.asarray)

    def __init__(self, coordinate_list: CloudCoords2D | CloudCoords3D):
        self.array = coordinate_list


class CoordinateGrid(AbstractCoordinates, strict=True):
    """
    A Pytree that wraps a coordinate grid.
    """

    array: ImageCoords | VolumeCoords = eqx.field(converter=jnp.asarray)

    def __init__(
        self,
        shape: tuple[int, int] | tuple[int, int, int],
        grid_spacing: float | ArrayLike = 1.0,
    ):
        self.array = make_coordinates(shape, grid_spacing)


class FrequencyGrid(AbstractCoordinates, strict=True):
    """
    A Pytree that wraps a frequency grid.
    """

    array: ImageCoords | VolumeCoords = eqx.field(converter=jnp.asarray)

    def __init__(
        self,
        shape: tuple[int, int] | tuple[int, int, int],
        grid_spacing: float | ArrayLike = 1.0,
        half_space: bool = True,
    ):
        self.array = make_frequencies(shape, grid_spacing, half_space=half_space)


class FrequencySlice(AbstractCoordinates, strict=True):
    """
    A Pytree that wraps a frequency slice.

    Unlike a `FrequencyGrid`, a `FrequencySlice` has the zero frequency
    component in the center.
    """

    array: VolumeSliceCoords = eqx.field(converter=jnp.asarray)

    def __init__(
        self,
        shape: tuple[int, int],
        grid_spacing: float | ArrayLike = 1.0,
        half_space: bool = True,
    ):
        frequency_slice = make_frequencies(shape, grid_spacing, half_space=half_space)
        if half_space:
            frequency_slice = jnp.fft.fftshift(frequency_slice, axes=(0,))
        else:
            frequency_slice = jnp.fft.fftshift(frequency_slice, axes=(0, 1))
        frequency_slice = jnp.expand_dims(
            jnp.pad(
                frequency_slice,
                ((0, 0), (0, 0), (0, 1)),
                mode="constant",
                constant_values=0.0,
            ),
            axis=2,
        )
        self.array = frequency_slice


def make_coordinates(
    shape: tuple[int, ...], grid_spacing: float | ArrayLike = 1.0
) -> Float[Array, "*shape len(shape)"]:
    """
    Create a real-space cartesian coordinate system on a grid.

    Arguments
    ---------
    shape :
        Shape of the voxel grid, with
        ``ndim = len(shape)``.
    grid_spacing :
        The grid spacing, in units of length.

    Returns
    -------
    coordinate_grid :
        Cartesian coordinate system in real space.
    """
    coordinate_grid = _make_coordinates_or_frequencies(
        shape, grid_spacing=grid_spacing, real_space=True, indexing="xy"
    )
    return coordinate_grid


def make_frequencies(
    shape: tuple[int, ...],
    grid_spacing: float | ArrayLike = 1.0,
    half_space: bool = True,
) -> Float[Array, "*shape len(shape)"]:
    """
    Create a fourier-space cartesian coordinate system on a grid.
    The zero-frequency component is in the beginning.

    Arguments
    ---------
    shape :
        Shape of the voxel grid, with
        ``ndim = len(shape)``.
    grid_spacing :
        The grid spacing, in units of length.
    half_space :
        Return a frequency grid on the half space.
        ``shape[-1]`` is the axis on which the negative
        frequencies are omitted.

    Returns
    -------
    frequency_grid :
        Cartesian coordinate system in frequency space.
    """
    frequency_grid = _make_coordinates_or_frequencies(
        shape,
        grid_spacing=grid_spacing,
        real_space=False,
        half_space=half_space,
        indexing="xy",
    )
    return frequency_grid


def cartesian_to_polar(freqs: ImageCoords, square: bool = False) -> tuple[Image, Image]:
    """
    Convert from cartesian to polar coordinates.

    Arguments
    ---------
    freqs :
        The cartesian coordinate system.
    square :
        If ``True``, return the square of the
        radial coordinate :math:`|r|^2`. Otherwise,
        return :math:`|r|`.
    """
    theta = jnp.arctan2(freqs[..., 0], freqs[..., 1])
    k_sqr = jnp.sum(jnp.square(freqs), axis=-1)
    if square:
        return k_sqr, theta
    else:
        kr = jnp.sqrt(k_sqr)
        return kr, theta


def _make_coordinates_or_frequencies(
    shape: tuple[int, ...],
    grid_spacing: float | ArrayLike = 1.0,
    real_space: bool = False,
    half_space: bool = True,
    indexing: str = "xy",
) -> Float[Array, "*shape len(shape)"]:
    ndim = len(shape)
    shape = (*shape[:2][::-1], *shape[2:]) if indexing == "xy" else shape
    coords1D = []
    for idx in range(ndim):
        if real_space:
            c1D = _make_coordinates_or_frequencies_1d(
                shape[idx], grid_spacing, real_space
            )
        else:
            if not half_space:
                rfftfreq = False
            else:
                if indexing == "xy" and ndim == 2:
                    rfftfreq = True if idx == 0 else False
                else:
                    rfftfreq = False if idx < ndim - 1 else True
            c1D = _make_coordinates_or_frequencies_1d(
                shape[idx], grid_spacing, real_space, rfftfreq
            )
        coords1D.append(c1D)
    coords = jnp.stack(jnp.meshgrid(*coords1D, indexing=indexing), axis=-1)

    return coords


def _make_coordinates_or_frequencies_1d(
    size: int,
    grid_spacing: float | ArrayLike,
    real_space: bool = False,
    rfftfreq: Optional[bool] = None,
) -> Float[Array, "size"]:
    """One-dimensional coordinates in real or fourier space"""
    if real_space:
        make_1d = (
            lambda size, dx: jnp.fft.fftshift(jnp.fft.fftfreq(size, 1 / dx)) * size
        )
    else:
        if rfftfreq is None:
            raise ValueError("Argument rfftfreq cannot be None if real_space=False.")
        else:
            fn = jnp.fft.rfftfreq if rfftfreq else jnp.fft.fftfreq
            make_1d = lambda size, dx: fn(size, grid_spacing)

    return make_1d(size, grid_spacing)
