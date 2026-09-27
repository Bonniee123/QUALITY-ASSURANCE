# Optional: use PyMySQL as MySQLdb when mysqlclient is not installed (common on Windows).
try:
    import pymysql  # noqa: F401

    pymysql.install_as_MySQLdb()
except ImportError:
    pass
