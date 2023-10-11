from setuptools import setup, find_packages

setup(name='pymodrev',
      version='1.0',
      author="Lourenco Matos",
      author_email="lourencodematos@gmail.com",
      url="https://github.com/Lourencom/pymodrev",
      description="A Python interface to the ModRev Software Tool",
      packages=find_packages(),
      install_requires=[
          "colomoto_jupyter >= 0.6.3"]
      )