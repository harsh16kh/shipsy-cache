"""Setuptools compatibility shim for editable installs."""

from setuptools import find_packages, setup


setup(
    name="shipsy-cache",
    version="1.0.0",
    description="Multi-tier caching library for Shipsy Engineering",
    packages=find_packages(include=["shipsy_cache", "shipsy_cache.*"]),
    include_package_data=True,
    install_requires=[
        "redis[asyncio]>=4.5.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0",
            "pytest-asyncio>=0.21",
            "pytest-cov>=4.0",
        ],
    },
)
