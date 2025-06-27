# ===== IMPORT REQUIRED MODULES ===============================================================================================
import yfinance as yf
import psycopg2
import psycopg2.extras # So cursor can return a dictionary
import matplotlib.pyplot as plt
from matplotlib import gridspec # For custom subplot layout
from datetime import datetime, timedelta # For historic stock price lookups
from typing import List, Dict, Any
import typer
from rich.console import Console
from rich.table import Table



# ===== DATABASE CONFIGURATION ===============================================================================================
# Set database configuration details
DB_CONFIG = {
    "host": "localhost",
    "database": "stock_portfolio",
    "user": "calvin",
    "password": "CS50P"
}



# ===== DATABASE CONNECTION & INITIALISATION ===============================================================================================
# Define function to connect to PostgreSQL using DB_CONFIG variable
def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)


# Define function that initialises the database and creates the tables if they don't exist
def init_db() -> None:
    conn = None
    try:
        # Connect to database
        with get_db_connection() as conn:
            # Set cursor so it returns dictionary
            with conn.cursor(cursor_factory = psycopg2.extras.DictCursor) as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS cash_transactions (
                        id SERIAL,
                        amount DECIMAL(15,2) NOT NULL,
                        type VARCHAR(4) CHECK(type IN ('DEP', 'WIT', 'BUY', 'SELL')),
                        date DATE DEFAULT CURRENT_DATE,
                        PRIMARY KEY(id)
                    );


                    CREATE TABLE IF NOT EXISTS transactions (
                        id SERIAL,
                        ticker VARCHAR(10) NOT NULL,
                        price DECIMAL(15, 2) NOT NULL CHECK(price > 0),
                        quantity DECIMAL(15, 2) NOT NULL CHECK(quantity > 0),
                        type VARCHAR(4) CHECK(type IN('BUY', 'SELL')),
                        cash_impact DECIMAL(15,2) NOT NULL,
                        date DATE DEFAULT CURRENT_DATE,
                        PRIMARY KEY(id)
                    );


                    CREATE TABLE IF NOT EXISTS holdings (
                        ticker VARCHAR(10),
                        quantity DECIMAL(15, 2) NOT NULL CHECK (quantity >= 0),
                        average_purchase_price DECIMAL(15, 2) NOT NULL CHECK(average_purchase_price > 0),
                        current_price DECIMAL(15, 2) NOT NULL CHECK(current_price > 0),
                        cost_basis DECIMAL(15, 2) NOT NULL CHECK(cost_basis >= 0),
                        current_value DECIMAL(15, 2) NOT NULL CHECK(current_value >= 0),
                        unrealised_delta DECIMAL(15, 2)
                            GENERATED ALWAYS AS (current_value - cost_basis) STORED,
                        PRIMARY KEY(ticker)
                    );


                    CREATE TABLE IF NOT EXISTS realised_delta (
                        transaction_id INTEGER,
                        ticker VARCHAR(10) NOT NULL,
                        delta DECIMAL(15, 2) NOT NULL,
                        date DATE DEFAULT CURRENT_DATE,
                        PRIMARY KEY(transaction_id),
                        FOREIGN KEY(transaction_id) REFERENCES transactions (id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_transactions_ticker ON transactions(ticker);
                    CREATE INDEX IF NOT EXISTS idx_realised_delta_ticker ON realised_delta(ticker);
                """)
                conn.commit()
    # Handle exceptions and return to user
    except psycopg2.Error as e:
        raise psycopg2.DatabaseError(f"Database initialisation failed: {e}")
    # Clean up and close the database connection
    finally:
        if conn is not None:
            conn.close()



# ===== YF STOCK FUNCTIONS ===============================================================================================
# Get stock price of a given ticker on a given date (if no date given, default is today's date)
def get_stock_price(ticker: str, date: str = None) -> float:
    stock = yf.Ticker(ticker)
    # Error handling for invalid ticker
    if stock.history(period='1d').empty:
        raise ValueError(f"Invalid ticker: {ticker}. Check your spelling.")
    if date:
        # Historical price lookup
        hist_data = stock.history(start = date, end = datetime.strptime(date, "%Y-%m-%d") + timedelta(days = 1)).iloc[0]
        price = hist_data["Close"]
    else:
        # Current price lookup
        price = stock.history(period = "1d")["Close"].iloc[-1] # Select only the Close price for today
    return round(price, 2)


# Get daily stock price and trading volume of a given ticker for the past year
def get_stock_historical(ticker: str) -> None:
    stock = yf.Ticker(ticker)
    # Error handling for invalid ticker
    if stock.history(period='1d').empty:
        raise ValueError(f"Invalid ticker: {ticker}. Check your spelling.")
    data = stock.history(period = "1y")
    # Create the figure and subplots for Close prices and Trading volume
    fig = plt.figure(figsize=(12, 6)) # Set (width, height)
    gs = gridspec.GridSpec(2, 1, height_ratios = [3, 1]) # 2 rows, 1 column (Top subplot is 3x taller than bottom)
    ax1 = plt.subplot(gs[0]) # 'Close price' subplot on top
    ax2 = plt.subplot(gs[1]) # 'Trading volume' subplot below
    # Plot the 'Close prices' and customise
    ax1.plot(data["Close"], label = f"{ticker} Close Price", color = "red")
    ax1.set_title(f"{ticker} Stock Price (Past Year)", fontsize = 16)
    ax1.set_ylabel("Price ($)", fontsize = 12)
    ax1.grid(True, linestyle = "--", alpha = 0.6)
    ax1.legend(loc = "upper left")
    # Plot the 'Trading volume' and customise
    ax2.bar(data.index, data["Volume"], label = f"{ticker} Trading Volume", color = "green", alpha = 0.6, width = 0.8)
    ax2.set_ylabel("Volume", fontsize = 12)
    ax2.grid(True, linestyle = "--", alpha = 0.6)
    ax2.legend(loc = "upper left")
    # Customise plot-level formatting
    for ax in [ax1, ax2]: # Prevent label cutoff
        plt.sca(ax)
        plt.xticks(rotation = 45)
    plt.xlabel("Date", fontsize = 12)
    plt.tight_layout()
    # Save the plot and let user know
    plt.savefig(f"{ticker}_1yr_plot.png", bbox_inches = "tight")
    print(f"✅ 🔍 Check your your current directory for {ticker}_1yr_plot.png")



# ===== PORTFOLIO (CORE) LOGIC ===============================================================================================
# Create class for Portfolio
class Portfolio:
    def __init__(self) -> None:
        self._conn = None


    def __enter__(self):
        self._conn = get_db_connection()
        return self


    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._conn:
            if exc_type: # If exception occurs
                self._conn.rollback() # Undo changes
            else: # Otherwise
                self._conn.commit() # Save changes
            self._conn.close() # Always close/release db connection


    def __str__(self) -> str:
        return (
            f"Portfolio value: ${self.total_value:.2f}\n"
            f"Cash balance: ${self.cash_balance:.2f}\n"
            f"Unrealised delta: ${self.unrealised_delta:.2f}\n"
            f"Realised delta: ${self.realised_delta:.2f}"
            )


    @property
    def cash_balance(self) -> float:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT COALESCE(SUM(amount), 0)
                FROM cash_transactions
                """
            )
            return cur.fetchone()[0] or 0.0


    @property
    def total_value(self) -> float:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT SUM(current_value) FROM holdings
                """
            )
            return cur.fetchone()[0] or 0.0


    @property
    def unrealised_delta(self) -> float:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT SUM(unrealised_delta) FROM holdings
                """
            )
            return cur.fetchone()[0] or 0.0


    @property
    def realised_delta(self) -> float:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT SUM(delta) FROM realised_delta
                """
            )
            return cur.fetchone()[0] or 0.0


    # Record a cash transaction
    def update_cash(self, amount: float, trans_type: str) -> bool:
        if amount <= 0:
            raise ValueError("The amount must be greater than zero")
        # Handle commands that aren't 'DEP' or 'WIT'
        if trans_type not in ("DEP", "WIT"):
            raise ValueError("Cash transaction must be 'DEP' or 'WIT'")
        balance = self.cash_balance
        if trans_type == "WIT" and amount > balance:
            raise ValueError(f"Insufficient funds to withdraw. You tried to withdraw ${amount:.2f}, but your balance is ${balance:.2f}")
        with self._conn.cursor() as cur:
            try:
                # Insert DEP / WIT into the cash_transactions table
                cur.execute(
                    """
                    INSERT INTO cash_transactions (amount, type)
                    VALUES(%s, %s)
                    """,
                    (amount if trans_type == "DEP" else -amount, trans_type)
                )
                return True
            except Exception as e:
                self._conn.rollback()
                print(f"❌ Error: {str(e)}")
                return False


    # Record a transaction
    def record_transaction(self, ticker: str, quantity: float, trans_type: str, date: str = None, manual_price: float = None) -> bool:
        # Input error handling
        if quantity <= 0:
            raise ValueError(f"Number of shares must be greater than zero.")
        if manual_price is not None and manual_price <= 0:
            raise ValueError(f"Price must be greater than zero.")
        if date:
            try:
                datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                raise ValueError(f"Date must be in YYY-MM-DD format.")
        # Open cursor to database
        with self._conn.cursor() as cur:
            # Get current price
            current_price = get_stock_price(ticker)
            # Set date if provided, otherwise default to today
            transaction_date = date if date else datetime.now().strftime("%Y-%m-%d")
            # Use manual_price if provided, else fetch price of given date (today by default, if date not specified)
            price = manual_price if manual_price else get_stock_price(ticker, transaction_date)
            # Check user's cash balance for transaction
            balance = self.cash_balance
            # Set value of cash impact
            value = (price * quantity)
            # Make sure user has enough cash for transaction, if BUY
            if trans_type == "BUY" and value > balance:
                raise ValueError(f"Insufficient funds. Needed ${value}, but only ${balance} available.")
            try:
                # Insert transaction into 'transactions' table
                cur.execute(
                    """
                    INSERT INTO transactions (ticker, price, quantity, type, cash_impact, date)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (ticker, price, quantity, trans_type, value if trans_type == "SELL" else -value, transaction_date)
                )
                transaction_id = cur.fetchone()[0]
                # Handle BUY vs SELL transaction
                if trans_type == "BUY":
                    self._update_holdings_on_buy(cur, ticker, quantity, price, current_price) # Upsert 'holdings' table with BUY transaction
                    self._update_cash_on_buy(cur, value) # Update cash balance for BUY transaction
                else:
                    self._validate_sale(cur, ticker, quantity) # Check if user has enough shares for SELL transaction
                    avg_price = self._get_average_purchase_price(cur, ticker)
                    self._update_holdings_on_sell(cur, ticker, quantity, price, current_price) # Update 'holdings' table with SELL transaction
                    self._update_cash_on_sell(cur, value) # Update cash balance for SELL transaction
                    realised_delta = float(quantity) * (float(price) - float(avg_price)) # Calculate realised_delta for sale
                    # Insert sale and realised delta into realised_delta table
                    cur.execute(
                        """
                        INSERT INTO realised_delta (transaction_id, ticker, delta, date)
                        VALUES(%s, %s, %s, %s
                        )
                        """,
                        (transaction_id, ticker, realised_delta, transaction_date)
                    )
                return True
            # Discard current SQL squery if any exceptions and return FALSE
            except Exception as e:
                self._conn.rollback()
                print(f"❌ Error: {str(e)}")
                return False


    # Upsert 'holdings' table on BUY
    def _update_holdings_on_buy(self, cur, ticker: str, quantity: float, price: float, current_price: float) -> None:
        cur.execute(
            """
            INSERT INTO holdings (ticker, quantity, average_purchase_price, current_price, cost_basis, current_value)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (ticker) DO UPDATE
            SET
                quantity = holdings.quantity + EXCLUDED.quantity,
                average_purchase_price = ROUND((holdings.quantity * holdings.average_purchase_price + EXCLUDED.quantity * EXCLUDED.average_purchase_price) / (holdings.quantity + EXCLUDED.quantity), 2),
                current_price = EXCLUDED.current_price,
                cost_basis = ROUND(holdings.cost_basis + (EXCLUDED.quantity * EXCLUDED.average_purchase_price), 2),
                current_value = ROUND((holdings.quantity + EXCLUDED.quantity) * EXCLUDED.current_price, 2)
            """,
            (ticker, quantity, price, current_price, quantity * price, quantity * current_price)
        )


    # Check if SELL transaction is valid / possible
    def _validate_sale(self, cur, ticker: str, quantity: float) -> None:
        # Check how many shares of a ticker user has
        cur.execute(
            """
            SELECT quantity FROM holdings WHERE ticker = %s
            """,
            (ticker,)
        )
        if (holding := cur.fetchone()) is None or float(holding[0]) < quantity: # Cast holding[0] as float as we are comparing it to quantity which is a float, and holding[0] is originally a decimal in postgresql
            raise ValueError(f"Insufficient shares of {ticker} to sell {quantity}. You have {float(holding[0]) if holding else 0} shares of {ticker}")


    # Update 'holdings' table on SELL
    """
    Must type cast all variables as numeric so Postgresql can handle the calculations and we don't run into
    a type error between float (variable) and decimal (postgresql). This is cleanest method I've found to handle
    """
    def _update_holdings_on_sell(self, cur, ticker: str, quantity: float, price: float, current_price: float) -> None:
        cur.execute(
            """
            UPDATE holdings
            SET
                quantity = holdings.quantity - %s::numeric,
                current_price = %s::numeric,
                cost_basis = ROUND((holdings.cost_basis / holdings.quantity) * (holdings.quantity - %s::numeric), 2),
                current_value = ROUND((holdings.quantity - %s::numeric) * %s::numeric, 2)
            WHERE ticker = %s
            """,
            (quantity, current_price, quantity, quantity, current_price, ticker)
        )


    # Get average purchase price
    def _get_average_purchase_price(self, cur, ticker: str) -> float:
        cur.execute(
            """
            SELECT average_purchase_price
            FROM holdings
            WHERE ticker = %s
            """,
            (ticker,)
        )
        return float(cur.fetchone()[0])


    # Insert BUY event into cash_transactions table
    def _update_cash_on_buy(self, cur, value: float) -> None:
        cur.execute(
            """
            INSERT INTO cash_transactions (amount, type)
            VALUES (%s, 'BUY')
            """,
            (-value,)
        )


    # Insert SELL event into cash_transactions table
    def _update_cash_on_sell(self, cur, value: float) -> None:
        cur.execute(
            """
            INSERT INTO cash_transactions (amount, type)
            VALUES (%s, 'SELL')
            """,
            (value,)
        )


    # Get transactions
    def get_transactions(self) -> List[Dict[str, Any]]:
        # Open cursor to database
        with self._conn.cursor(cursor_factory = psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """
                SELECT to_char(date, 'YYYY-MM-DD') AS date, type, ticker, price, quantity
                FROM transactions
                ORDER BY date DESC
                """
            )
            return cur.fetchall()


    # Get transactions of one stock
    def get_stock_transactions(self, ticker: str) -> List[Dict[str, Any]]:
        # Open cursor to database
        with self._conn.cursor(cursor_factory = psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """
                SELECT to_char(date, 'YYYY-MM-DD') AS date, type, ticker, price, quantity
                FROM transactions
                WHERE ticker = %s
                ORDER BY date DESC
                """,
                (ticker,)
            )
            return cur.fetchall()


    # Get holdings
    def get_holdings(self) -> List[Dict[str, Any]]:
        # Open cursor to database
        with self._conn.cursor(cursor_factory = psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """
                SELECT
                    a.ticker,
                    a.quantity,
                    a.average_purchase_price,
                    a.current_price,
                    a.cost_basis,
                    a.current_value,
                    a.unrealised_delta,
                    COALESCE(SUM(b.delta), 0) AS realised_delta
                FROM holdings a
                LEFT JOIN realised_delta b
                ON a.ticker = b.ticker
                GROUP BY a.ticker
                ORDER BY ticker ASC
                """
            )
            return cur.fetchall()



# ===== COMMAND-LINE INTERFACE (CLI) DISPLAY FUNCTIONS ===============================================================================================
# Create app
app = typer.Typer()
# Initialise console
console = Console(soft_wrap = True)


# Display holdings in CLI
def display_holdings() -> None:
    with Portfolio() as portfolio:
        holdings = portfolio.get_holdings()
        # Create table to display
        table = Table(title = "Your Portfolio")
        table.add_column("Ticker", style = "cyan")
        table.add_column("Shares", justify = "right")
        table.add_column("Avg Purchase Price", justify = "right")
        table.add_column("Current Price", justify = "right")
        table.add_column("Cost-basis", style = "red", justify = "right")
        table.add_column("Current Value", style = "green", justify = "right")
        table.add_column("Unrealised", style = "green", justify = "right")
        table.add_column("Realised", style = "green", justify = "right")
        # Populate table
        for stock in holdings:
            table.add_row(
                stock["ticker"],
                f"{stock['quantity']:.2f}",
                f"{stock['average_purchase_price']:.2f}",
                f"{stock['current_price']:.2f}",
                f"{stock['cost_basis']:.2f}",
                f"{stock['current_value']:.2f}",
                f"{stock['unrealised_delta']:.2f}",
                f"{stock['realised_delta'] or 0:.2f}"
            )
        # Print table to user
        console.print(table)


# Display all transactions of a specific stock in CLI
def display_stock_transactions(ticker: str) -> None:
    with Portfolio() as portfolio:
        transactions = portfolio.get_stock_transactions(ticker)
        # Create table to display
        table = Table(title = "Your Transactions")
        table.add_column("Date")
        table.add_column("Transaction Type")
        table.add_column("Ticker", style = "cyan")
        table.add_column("Price", justify = "right")
        table.add_column("Shares", justify = "right")
        # Populate table
        for action in transactions:
            table.add_row(
                action["date"],
                action["type"],
                action["ticker"],
                f"{action['price']:.2f}",
                f"{action['quantity']:.2f}"
            )
        # Print table to user
        console.print(table)


# Display all transactions in CLI
def display_all_transactions() -> None:
    with Portfolio() as portfolio:
        transactions = portfolio.get_transactions()
        # Create table to display
        table = Table(title = "Your Transactions")
        table.add_column("Date")
        table.add_column("Transaction Type")
        table.add_column("Ticker", style = "cyan")
        table.add_column("Price", justify = "right")
        table.add_column("Shares", justify = "right")
        # Populate table
        for action in transactions:
            table.add_row(
                action["date"],
                action["type"],
                action["ticker"],
                f"{action['price']:.2f}",
                f"{action['quantity']:.2f}"
            )
        # Print table to user
        console.print(table)


# Output a PNG with specific stock information for past
def display_stock_info(ticker: str) -> None:
    get_stock_historical(ticker)



# ===== TYPER CLI COMMANDS ===============================================================================================
# Create default behaviour
@app.callback(invoke_without_command = True)
def main(ctx: typer.Context) -> None:
    """Stock Portfolio Manager"""
    if ctx.invoked_subcommand is None:
        # This runs when no command is specified
        display_holdings()
        with Portfolio() as portfolio:
            console.print(f"[bold green]{portfolio}[/bold green]")


# Deposit cash
@app.command()
def deposit(amount: float) -> None:
    """Deposit cash into your balance, which you can use to buy stocks"""
    with Portfolio() as portfolio:
        if portfolio.update_cash(amount, "DEP"):
            print(f"✅ Deposited ${amount:.2f} into your portfolio")
        else:
            print(f"❌ Cash update failed")


# Withdraw cash
@app.command()
def withdraw(amount: float) -> None:
    """Withdraw cash from your balance"""
    with Portfolio() as portfolio:
        if portfolio.update_cash(amount, "WIT"):
            print(f"✅ Withdrew ${amount:.2f} from your portfolio")
        else:
            print(f"❌ Cash update failed")


# Buy stocks
@app.command()
def buy(ticker: str, shares: float, date: str = None, price: float = None) -> None:
    """Buy a stock: Provide ticker (str) and number of shares (float)"""
    # Initialise portfolio
    with Portfolio() as portfolio:
        # Get stock price of ticker (current / historical)
        if portfolio.record_transaction(ticker, shares, "BUY", date, price):
            print(f"✅ Bought {shares} of {ticker} at ${price or get_stock_price(ticker, date):.2f} per share")
        else:
            print(f"❌ Transaction failed")


# Sell stocks
@app.command()
def sell(ticker: str, shares: float, date: str = None, price: float = None) -> None:
    """Sell a stock: Provide ticker (str) and number of shares (float)"""
    # Initialise portfolio
    with Portfolio() as portfolio:
        # Get stock price of ticker (current / historical)
        try:
            if portfolio.record_transaction(ticker, shares, "SELL", date, price):
                print(f"✅ Sold {shares} of {ticker} at ${price or get_stock_price(ticker, date):.2f} per share")
        except ValueError as e:
            print(f"❌ {str(e)}")


# Show all portfolio holdings
@app.command()
def all_holdings() -> None:
    """Display all your holdings and current value of portfolio"""
    display_holdings()
    with Portfolio() as portfolio:
        console.print(f"[bold green]{portfolio}[/bold green]")


# Show specific stock holdings
@app.command()
def stock_transactions(ticker: str) -> None:
    """Display all transactions of a specific stock: Provide ticker (str)"""
    display_stock_transactions(ticker)


# Show all transactions
@app.command()
def all_transactions() -> None:
    """Display all transactions"""
    display_all_transactions()


# Output a PNG of the past year historical close prices and trading volume for a given ticker
@app.command()
def stock_info(ticker: str) -> None:
    """Display prices and trading volume of stock in past year as an image: Provide ticker (str)"""
    display_stock_info(ticker)



# ===== MAIN ===============================================================================================
if __name__ == "__main__":
    init_db()   # Initialise database tables
    app()
