from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = f.read().strip().split("\n")

# get version from __version__ variable in tr_tradehub/__init__.py
from tr_tradehub import __version__ as version

setup(
    name="tr_tradehub",
    version=version,
    description="TR-TradeHub B2B/B4B/C2C Marketplace Platform",
    author="TR-TradeHub",
    author_email="info@tr-tradehub.com",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=install_requires,
    python_requires=">=3.10",
)
