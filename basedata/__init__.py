"""Base data checker: checks base data files that are placed in a local or OneDrive-synced folder.

The module reads each file's metadata, checks it against the project's rule set (code checks plus an
optional AI check), keeps a register in a local SQLite file, asks uploaders for missing information, and
lets a reviewer approve files and export the register to Excel.
"""

__version__ = "0.2.0"
