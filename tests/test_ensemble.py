import pytest

from functools import partial

import jax
import jax.numpy as jnp
import jax.tree_util as jtu
import equinox as eqx

from cryojax.simulator import DiscreteEnsemble, DiscreteConformation


def test_conformation(density, pose, scattering):
    density = tuple([density for _ in range(3)])
    ensemble = DiscreteEnsemble(density, pose, conformation=DiscreteConformation(0))
    _ = scattering(ensemble)


def test_conformation_vmap(density, pose, scattering):
    # Build Ensemble
    cls = type(density)
    stacked_density = tuple([density for _ in range(3)])
    ensemble = DiscreteEnsemble(
        stacked_density,
        pose,
        conformation=DiscreteConformation(jnp.asarray((0, 1, 2, 1, 0))),
    )
    # Setup vmap
    is_vmap = lambda x: isinstance(x, DiscreteConformation)
    to_vmap = jtu.tree_map(is_vmap, ensemble, is_leaf=is_vmap)
    vmap, novmap = eqx.partition(ensemble, to_vmap)

    @partial(jax.vmap, in_axes=[0, None, None])
    def compute_conformation_stack(vmap, novmap, scattering):
        ensemble = eqx.combine(vmap, novmap)
        return scattering(ensemble)

    # Vmap over conformations
    image_stack = compute_conformation_stack(vmap, novmap, scattering)
    assert image_stack.shape[0] == ensemble.conformation.get().shape[0]
