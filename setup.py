from setuptools import setup, find_packages

pkg_name = "kinobot"


def read_file(fname):
    with open(fname, "r") as f:
        return f.read()


requirements = read_file("requirements.txt").strip().split()


setup(
    name=pkg_name,
    version="0.9.1",
    author="Vitiko",
    author_email="vhnz98@gmail.com",
    description="Core of the ultimate Facebook bot for cinephiles",
    long_description=read_file("README.md"),
    long_description_content_type="text/markdown",
    url="https://github.com/vitiko98/kinobot",
    #    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "kinobot = kinobot:cli",
            "kino = kinobot:cli",
        ],
    },
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU General Public License (GPL)",
    ],
    python_requires=">=3.6",
)
