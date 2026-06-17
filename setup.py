from setuptools import setup, find_packages

setup(
    name="VecStorm",
    version="2026.6.1",
    packages=find_packages(),
    install_requires=[
        "jax",
        "chex",
        "numpy",
        "stormpy",
        "paynt"
    ],
    author="Martin Kurecka & David Hudak",
    description="A jax based compiler for Storm environments.",
)
