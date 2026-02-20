from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = f.read().strip().split("\n")

# get version from __version__ variable in tradehub_seller/__init__.py
from tradehub_seller import __version__ as version

setup(
    name="tradehub_seller",
    version=version,
    description="Seller lifecycle management layer for TradeHub Marketplace",
    author="TradeHub Team",
    author_email="dev@tradehub.local",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=install_requires,
)
