import sqlite3


class DBLink:
    """
    This library takes care of opening and closing connection to a database when needed,
    and tries to remove as much boilerplate code as possible.
    """

    def __init__(self, dbname):
        """
        Prepares the DBLink variables
        :param dbname:
        """
        self.dbname = dbname
        self.connection = None
        self.cursor = None
        self.settings = {}
        self.initialize()
        self.load_settings()


    def connect(self):
        """
        Connects to the database
        :return: None
        """
        self.connection = sqlite3.connect(self.dbname)
        self.cursor = self.connection.cursor()

    def close(self):
        """
        Closes the connection
        :return: None
        """
        self.connection.commit()
        self.connection.close()
        self.connection = None
        self.cursor = None

    def execute(self, *args):
        """
        A simple extension of cursor.execute
        :param args:  Query and its parameters
        :return:
        """
        self.cursor.execute(*args)

    def execute_many(self, *args):
        """
        A simple extension of cursor.executemany
        :param args:  Query and its parameters
        :return:
        """
        self.cursor.executemany(*args)
