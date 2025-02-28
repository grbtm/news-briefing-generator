import sqlite3


class DatabaseManager:
    """
    A class to manage SQLite database operations.
    Methods
    -------
    __init__(db_path: str) -> None
        Initializes the database connection.
    close() -> None
        Commits changes and closes the database connection.
    execute_ddl(command: str) -> None
        Executes a DDL (Data Definition Language) command.
    run_query(query: str) -> list
        Executes a query and returns the results.
    insert(table: str, columns: list, values: list) -> None
        Inserts a row into the specified table.
    select(table: str, columns: list, condition: str | None = None) -> list
        Selects rows from the specified table with an optional condition.
    update(table: str, columns: list, values: list, condition: str) -> None
        Updates rows in the specified table based on a condition.
    delete(table: str, condition: str) -> None
        Deletes rows from the specified table based on a condition.
    """

    def __init__(self, db_path: str) -> None:
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    def execute_ddl(self, command: str) -> None:
        self.cursor.execute(command)
        self.conn.commit()

    def run_query(self, query: str) -> list:
        self.cursor.execute(query)
        return self.cursor.fetchall()

    def insert(self, table: str, columns: list, values: list) -> None:
        placeholders = ", ".join(["?"] * len(columns))
        columns_str = ", ".join(columns)
        query = f"INSERT OR IGNORE INTO {table} ({columns_str}) VALUES ({placeholders})"
        self.cursor.execute(query, values)
        self.conn.commit()

    def insert_many(self, table: str, columns: list, values: list[tuple]) -> None:
        placeholders = ", ".join(["?"] * len(columns))
        columns_str = ", ".join(columns)
        query = f"INSERT OR IGNORE INTO {table} ({columns_str}) VALUES ({placeholders})"
        self.cursor.executemany(query, values)
        self.conn.commit()

    def select(self, table: str, columns: list, condition: str | None = None) -> list:
        query = f"SELECT {', '.join(columns)} FROM {table}"
        if condition:
            query += f" WHERE {condition}"
        self.cursor.execute(query)
        return self.cursor.fetchall()

    def delete(self, table: str, condition: str) -> None:
        query = f"DELETE FROM {table} WHERE {condition}"
        self.cursor.execute(query)
        self.conn.commit()

    def get_column_names(self, table: str) -> list:
        query = f"PRAGMA table_info({table})"
        self.cursor.execute(query)
        return [row[1] for row in self.cursor.fetchall()]

    def update_many(
        self,
        table: str,
        columns: list[str],
        values: list[tuple],
        condition_columns: str | list[str],
    ) -> None:
        """Update multiple rows in a table based on condition columns.

        Args:
            table: Name of the table to update
            columns: List of column names to update
            values: List of tuples containing update values followed by condition values
            condition_columns: Column name(s) to use in WHERE clause
        """
        # Handle single string condition column
        if isinstance(condition_columns, str):
            condition_columns = [condition_columns]

        # Build SET and WHERE clauses
        set_clause = ", ".join([f"{col} = ?" for col in columns])
        where_clause = " AND ".join([f"{col} = ?" for col in condition_columns])

        query = f"UPDATE {table} SET {set_clause} WHERE {where_clause}"
        self.cursor.executemany(query, values)
        self.conn.commit()
