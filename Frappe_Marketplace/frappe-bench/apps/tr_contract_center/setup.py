from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = f.read().strip().split("\n")

from tr_contract_center import __version__ as version

setup(
    name="tr_contract_center",
    version=version,
    description="Contract Management System with Digital/Wet Signature Support",
    author="TR TradeHub",
    author_email="info@tr-tradehub.com",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=install_requires,
    python_requires=">=3.10",
)
