"""Cogsdale conversion platform engine.

The same code runs on a laptop (local parquet + SQL Server LocalDB) and in a Microsoft Fabric
Python notebook (OneLake Delta tables + Fabric SQL database). Behaviour comes from the client's
YAML specs (take, reshape, crosswalks); the code holds no client-specific logic.
"""
__version__ = "0.1.0"
