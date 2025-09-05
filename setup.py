from setuptools import find_packages, setup

with open("VERSION", "r") as version_file:
    version = version_file.read().strip()

setup(
    name="genserver",
    version=version,
    packages=find_packages(include=["genserver"]),  # Find packages under genserver/
    install_requires=[],  # No dependencies for now
    description="Python GenServer implementation inspired by Erlang/OTP",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/ourway/genserver",  # Replace with your repo URL - UPDATE THIS!
    author="Farshid Ashouri",
    author_email="farsheed.ashouri@gmail.com",
    license="MIT",
    license_files=("LICENSE",),  # Explicitly include the LICENSE file - KEEP THIS!
    classifiers=[
        "Development Status :: 3 - Alpha",  # Or '4 - Beta', '5 - Production/Stable' as you mature
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Software Development :: Libraries :: Application Frameworks",
        "Topic :: System :: Networking",
    ],
)
