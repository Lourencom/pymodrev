from setuptools import setup, find_packages

NAME = 'modrev'

setup(name=NAME,
    version='9999',
    author = "Lourenco Matos",
    author_email = "lourencodematos@gmail.com",
    url = "https://github.com/Lourencom/modrev-python",
    description = "Python interface to ModRev",
    long_description = """Provides interface to ModRev""",
    install_requires = [
        "py4j",
        "colomoto_jupyter >= 0.6.3",
    ],
    py_modules = ["modrev_setup"],
)
