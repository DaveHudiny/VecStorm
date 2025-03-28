from functools import partial
from typing import List

import jax
import jax.numpy as jnp
import chex

from .sparse_array import SparseArray


@chex.dataclass
class States:
    vertices: chex.Array
    steps: chex.Array


@chex.dataclass
class ResetInfo:
    states: States
    observations: chex.Array
    allowed_actions: chex.Array
    metalabels: chex.Array
    integer_observations: chex.Array = None


@chex.dataclass
class StepInfo:
    states: States
    observations: chex.Array
    rewards: chex.Array
    done: chex.Array
    allowed_actions: chex.Array
    metalabels: chex.Array
    truncated: chex.Array
    integer_observations: chex.Array = None


@chex.dataclass
class Simulator:
    id: int

    initial_state: int
    max_outcomes: int
    max_steps: int
    random_init: bool

    transitions: SparseArray
    rewards: SparseArray
    observations: chex.Array
    sinks: chex.Array
    allowed_actions: chex.Array
    metalabels: chex.Array
    labels: chex.Array

    action_labels: List[str]
    observation_labels: List[str]

    state_values: chex.Array
    state_labels: chex.Array

    FREE_ID = 0

    def __hash__(self):
        return self.id

    @staticmethod
    def get_free_id():
        Simulator.FREE_ID += 1
        return Simulator.FREE_ID

    def sample_next_vertex(self: "Simulator", vertex, action, rng_key):
        l, r = self.transitions.get_row_range(vertex, action)
        entry_indices = jnp.arange(0, self.max_outcomes, 1) + l
        mask = entry_indices < r
        probs = jnp.where(mask, self.transitions.data[entry_indices], 0)
        idx = jax.random.choice(key=rng_key, a=entry_indices, p=probs)
        return self.transitions.indices[idx], idx

    def get_observation(self: "Simulator", vertex):
        return self.observations[vertex]

    def get_reward(self: "Simulator", entry_idx):
        return self.rewards.data[entry_idx]

    def is_done(self: "Simulator", vertex):
        return self.sinks[vertex]

    def get_init_states(self: "Simulator", states, rng_key) -> States:

        if self.random_init == False:
            vertices = states.vertices.at[:].set(self.initial_state)
        else:
            vertices = jax.random.randint(rng_key, states.vertices.shape, 0, len(self.sinks))
        
        return States(
            vertices = vertices,
            steps = jnp.zeros_like(states.steps),
        )

    @partial(jax.jit, static_argnums=0)
    def reset(self: "Simulator", states: States, rng_key) -> ResetInfo:
        new_states = self.get_init_states(states, rng_key)
        observations = jax.vmap(lambda s: self.get_observation(s))(new_states.vertices)
        return ResetInfo(
            states = new_states,
            observations = observations,
            allowed_actions = self.allowed_actions[new_states.vertices],
            metalabels = self.metalabels[new_states.vertices],
        )

    @partial(jax.jit, static_argnums=0)
    def step(self: "Simulator", states, actions, rng_key) -> StepInfo:
        key1, key2 = jax.random.split(rng_key)
        prev_done = self.sinks[states.vertices]
        new_vertices, new_vertex_idxs = jax.vmap(lambda s, a, k: self.sample_next_vertex(s, a, k))(states.vertices, actions, jax.random.split(key1, len(actions)))
        # Compute rewards of the transitions s -> a -> s'
        rewards = jax.vmap(lambda new_s: self.get_reward(new_s))(new_vertex_idxs)
        steps = states.steps + 1
        trunc = steps >= self.max_steps
        done = self.sinks[new_vertices] | trunc
        # Reset done state s' to initial state i
        if not self.random_init:
            key2 = None
        vertices_after_reset = jnp.where(prev_done, self.get_init_states(states, rng_key=key2).vertices, new_vertices)
        done = jnp.where(prev_done, False, done)
        steps_after_reset = jnp.where(done, 0, steps)
        rewards = jnp.where(prev_done, 0, rewards)
        
        # Compute observation of states after reset (s' or i)
        observations = jax.vmap(lambda s: self.get_observation(s))(vertices_after_reset)
        metalabels = self.metalabels[vertices_after_reset]

        allowed_actions = self.allowed_actions[vertices_after_reset]
        allowed_actions = jnp.where(jnp.tile(jnp.reshape(done, (-1, 1)), (1, allowed_actions.shape[1])), 
                                    jnp.ones_like(allowed_actions), allowed_actions)
            
        return StepInfo(
            states = States(vertices = vertices_after_reset, steps = steps_after_reset),
            observations = observations,
            rewards = rewards,
            done = done,
            allowed_actions = self.allowed_actions[vertices_after_reset],
            truncated = trunc,
            metalabels = metalabels,
        )
    
    def set_max_steps(self, max_steps):
        self.max_steps = max_steps
