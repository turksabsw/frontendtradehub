from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = f.read().strip().split("\n")

# get version from __version__ variable in tr_consent_center/__init__.py
from tr_consent_center import __version__ as version

setup(
    name="tr_consent_center",
    version=version,
    description="KVKK/GDPR Compliant Consent Management System for Frappe Framework",
    author="TR TradeHub",
    author_email="info@tr-tradehub.com",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=install_requires,
    python_requires=">=3.10",
)
