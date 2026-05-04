# setup.py
from setuptools import setup, find_packages

setup(
    name="nifty-algo-trader",
    version="1.0.0",
    description="Autonomous Nifty/BankNifty/FinNifty options buying bot (paper trade)",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=open("requirements.txt").read().splitlines(),
    entry_points={
        "console_scripts": [
            "algo-trader=main:main",
        ],
    },
)
