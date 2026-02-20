from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = f.read().strip().split("\n")

# Get version from module
from mock_data_engine import __version__ as version

setup(
    name="mock_data_engine",
    version=version,
    description="Mock Data Engine for Frappe Framework",
    author="Auto Claude",
    author_email="noreply@example.com",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=install_requires,
    python_requires=">=3.10",
)
