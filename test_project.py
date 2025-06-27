# ===== Import required modules ===============================================================================================
import pytest
import psycopg2
import pandas as pd
from decimal import Decimal
from datetime import datetime, timedelta
from typer.testing import CliRunner
from project import DB_CONFIG, Portfolio, get_db_connection, init_db, get_stock_price, app



# ===== Constants for testing ===============================================================================================
TEST_TICKER = "TEST"
TEST_PRICE = Decimal('100.00')
runner = CliRunner() # Initialise CliRunner for Typer command and display testing



# ===== Fixtures ===============================================================================================
# Create a ficture for database configuration to use across all tests (session), to ensure same database is used for all tests
@pytest.fixture(scope = "session", autouse = True)
def test_db_config():
    """Override DB config for testing"""
    original_config = DB_CONFIG.copy()
    DB_CONFIG.update({
        "host": "localhost",
        "database": "stock_portfolio",
        "user": "calvin",
        "password": "CS50P"
    })


# Create a fixture across all tests in file (module) that initialises a DB, so all tests can use the same database
@pytest.fixture(scope = "module", autouse = True)
def initialise_db():
    """Initialise test database once for all tests"""
    init_db()
    try:
        yield
    finally: # Cleanup happens even if tests fail
        clean_database() # Cleanup after all tests complete


# Create a fixture that cleans the database, and can be called by each test before testing
@pytest.fixture()
def clean_db():
    """Clean database before each test"""
    clean_database()


# Create a fixture that actually cleans the database. Seperating the calling and cleaning logic to allow for more flexibility
def clean_database():
    """Helper function to clean test data"""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM realised_delta;")
            cur.execute("DELETE FROM transactions;")
            cur.execute("DELETE FROM holdings;")
            cur.execute("DELETE FROM cash_transactions;")


# Create a fixture that rolls back transactions for atomic tests
@pytest.fixture()
def db_transaction(clean_db):
    """Provide transaction rollback after each test"""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            yield cur
            conn.rollback() # Undo all test changes


# Create a fixture that makes it so that instantiates a new portfolio and deposits it with 10000 cash from the get go for testing
@pytest.fixture()
def funded_portfolio(db_transaction): # Add db_transaction dependency
    """Portfolio with starting cash"""
    with Portfolio() as p:
        clean_database()
        p.update_cash(10000, "DEP")
        yield p



# ===== Mock helpers ===============================================================================================
# Create a mock helper function for the yfinance calls
@pytest.fixture
def mock_yfinance(monkeypatch):
    """Mock yfinance to simulate invalid ticker responses"""
    class MockTicker:
        def history(self, period = None):
            if period == '1d':
                return pd.DataFrame()  # Empty DataFrame simulates invalid ticker
            return pd.DataFrame({'Close': [100]})  # Default valid response

    monkeypatch.setattr('yfinance.Ticker', lambda _: MockTicker())

# Create a mock helper function for the stock price yfinance call
@pytest.fixture
def mock_stock_price(monkeypatch):
    """Mock get_stock_price_function"""
    def mock_get_price(ticker, date = None):
        if ticker == TEST_TICKER:
            return TEST_PRICE
        return Decimal('50.0') # Default to 50 for other tickers (not TEST_TICKER)
    monkeypatch.setattr("project.get_stock_price", mock_get_price)



# ===== Tests ===============================================================================================
def test_get_db_connection():
    """Test that database connection can be established"""
    conn = None
    try:
        conn = get_db_connection()
        assert conn is not None
        assert conn.status == psycopg2.extensions.STATUS_READY
    finally:
        if conn:
            conn.close()


def test_init_db():
    """Test that database tables are created"""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                """
            )
            tables = [row[0] for row in cur.fetchall()]
            expected_tables = [
                'cash_transactions',
                'transactions',
                'holdings',
                'realised_delta'
            ]
            for table in expected_tables:
                assert table in tables


def test_update_cash_deposit(db_transaction, funded_portfolio):
    """Test deposit of cash increases cash balance"""
    initial_cash = funded_portfolio.cash_balance
    funded_portfolio.update_cash(500, "DEP")
    assert funded_portfolio.cash_balance == initial_cash + 500


def test_update_cash_withdrawal(db_transaction, funded_portfolio):
    """Test withdrawal of cash decreases cash balance"""
    initial_cash = funded_portfolio.cash_balance
    funded_portfolio.update_cash(500, "WIT")
    assert funded_portfolio.cash_balance == initial_cash - 500


def test_insufficient_funds_withdrawal(db_transaction, funded_portfolio):
    """Test cannot withdraw more than the cash balance"""
    with pytest.raises(ValueError, match = "Insufficient funds"):
        funded_portfolio.update_cash(20000,"WIT")


def test_record_transaction_buy_stock(db_transaction, funded_portfolio, mock_stock_price):
    """Test buying stock updates holdings and cash"""
    initial_cash = funded_portfolio.cash_balance
    funded_portfolio.record_transaction(TEST_TICKER, 10, "BUY")
    # Verify cash was deducted
    assert funded_portfolio.cash_balance == initial_cash - 10 * TEST_PRICE
    # Verify holding was updated
    with funded_portfolio._conn.cursor() as cur:
        cur.execute(
            "SELECT quantity FROM holdings WHERE ticker = %s"
            , (TEST_TICKER,)
        )
        result = cur.fetchone()
        assert result[0] == 10


def test_record_transaction_sell_stock(db_transaction, funded_portfolio, mock_stock_price):
    """Test selling stock updates holdings and cash"""
    funded_portfolio.record_transaction(TEST_TICKER, 10, "BUY")
    initial_cash = funded_portfolio.cash_balance
    funded_portfolio.record_transaction(TEST_TICKER, 5, "SELL")
    # Verify cash was added to
    assert funded_portfolio.cash_balance == initial_cash + (5 * TEST_PRICE)
    # Very holdings was updated
    with funded_portfolio._conn.cursor() as cur:
        cur.execute(
            "SELECT quantity FROM holdings WHERE ticker = %s"
            , (TEST_TICKER,)
        )
        result = cur.fetchone()
        assert result[0] == 5


def test_record_transaction_realised_gain(db_transaction, funded_portfolio, mock_stock_price):
    """Test realised gain calculation"""
    # Buy then sell at higher price
    funded_portfolio.record_transaction(TEST_TICKER, 10, "BUY", manual_price=100)
    funded_portfolio.record_transaction(TEST_TICKER, 10, "SELL", manual_price=150)
    # Check realised delta
    with funded_portfolio._conn.cursor() as cur:
        cur.execute("SELECT SUM(delta) FROM realised_delta")
        assert cur.fetchone()[0] == 500  # (150-100)*10


def test_portfolio_value(db_transaction, funded_portfolio, mock_stock_price):
    """Test portfolio value calculation"""
    funded_portfolio.record_transaction(TEST_TICKER, 10, "BUY")
    # Verify value is the sum of all current holdings
    expected_value = TEST_PRICE * 10
    assert funded_portfolio.total_value == expected_value


def test_portfolio_summary(funded_portfolio, mock_stock_price):
    """Test portfolio summary string"""
    funded_portfolio.record_transaction(TEST_TICKER, 10, "BUY")
    summary = str(funded_portfolio)
    assert "Portfolio value" in summary
    assert "Cash balance" in summary
    assert "Unrealised delta" in summary
    assert "Realised delta" in summary


def test_fractional_shares(funded_portfolio, mock_stock_price):
    """Test fractional share transactions"""
    funded_portfolio.record_transaction(TEST_TICKER, Decimal('0.5'), "BUY")
    with funded_portfolio._conn.cursor() as cur:
        cur.execute(
            "SELECT quantity FROM holdings WHERE ticker = %s"
            , (TEST_TICKER,)
        )
        assert Decimal(str(cur.fetchone()[0])) == Decimal(0.5)


def test_zero_quantity_transaction(funded_portfolio):
    """Test zero quantity transactions are rejected"""
    with pytest.raises(ValueError, match = "Number of shares must be greater than zero"):
        funded_portfolio.record_transaction(TEST_TICKER, 0, "BUY")


def test_invalid_ticker(mock_yfinance):
    """Test invalid ticker handling"""
    with pytest.raises(ValueError, match = "Invalid ticker"):
        get_stock_price("INVALIDTICKER")


def test_average_price(db_transaction, funded_portfolio, mock_stock_price):
    """Test average purchase price calculation"""
    # Buy shares at different prices
    funded_portfolio.record_transaction(TEST_TICKER, 10, "BUY", manual_price = 100)
    funded_portfolio.record_transaction(TEST_TICKER, 10, "BUY", manual_price = 200)
    # Verify average price is correct
    with funded_portfolio._conn.cursor() as cur:
        cur.execute(
            "SELECT average_purchase_price FROM holdings WHERE ticker = %s"
            , (TEST_TICKER,)
        )
        result = cur.fetchone()
        assert result[0] == 150 # (10 *100 + 10*200)/20 = 150


def test_deposit(funded_portfolio):
    """Test deposit CLI command"""
    result = runner.invoke(app, ["deposit", "1000"])
    assert result.exit_code == 0
    assert "Deposited $1000.00" in result.stdout


def test_display_holdings(funded_portfolio, monkeypatch):
    # Mock stock price consistently
    monkeypatch.setattr('project.get_stock_price', lambda *args: Decimal('100'))
    # Record transaction (with explicit commit)
    funded_portfolio.record_transaction("TEST", Decimal('10'), "BUY")
    funded_portfolio._conn.commit()  # Force commit
    # Verify data exists in database
    with funded_portfolio._conn.cursor() as cur:
        cur.execute("SELECT * FROM holdings")
        print("\nDatabase holdings:", cur.fetchall())
        cur.execute("SELECT * FROM transactions")
        print("Database transactions:", cur.fetchall())
    # Invoke command
    result = CliRunner().invoke(app, ["all-holdings"])
    print("\nCLI Output:", repr(result.output))
    # Verify
    assert result.exit_code == 0
    assert "TEST" in result.output
    assert "10.00" in result.output
    assert "1000.00" in result.output.replace(",", "")  # Handle possible thousands separators


def test_display_all_transactions(funded_portfolio, monkeypatch):
    # Mock stock price consistently
    monkeypatch.setattr('project.get_stock_price', lambda *args: Decimal('100'))
    # Record transaction (with explicit commit)
    funded_portfolio.record_transaction("TEST", Decimal('10'), "BUY")
    funded_portfolio._conn.commit()  # Force commit
    # Verify data exists in database
    with funded_portfolio._conn.cursor() as cur:
        cur.execute("SELECT * FROM holdings")
        print("\nDatabase holdings:", cur.fetchall())
        cur.execute("SELECT * FROM transactions")
        print("Database transactions:", cur.fetchall())
    # Invoke command
    result = CliRunner().invoke(app, ["all-transactions"])
    print("\nCLI Output:", repr(result.output))
    # Verify
    assert result.exit_code == 0
    assert "Your Transactions" in result.output
    assert "TEST" in result.output
    assert "10" in result.output
    assert "BUY" in result.output


