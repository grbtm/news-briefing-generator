import os


def get_sql_command(filename: str) -> str:
    """Read SQL command from SQL file."""
    fpath = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 
        "DDL",
        filename
    )
    
    with open(fpath, 'r') as file:
        return file.read()