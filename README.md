# STOCK PORTFOLIO TRACKER
### Video Demo: https://youtu.be/vg21xzxCQaM
### Description:
A command-line interface application that allows a user to manage their stock portfolio. Users are able to look up stock information, deposit and withdraw cash, record transactions and ask the app to display information about their portfolio back to them.


#### Motivation
I currently use an app (MyStocks <https://apps.apple.com/sa/app/my-stocks-portfolio-market/id923544282?l=th> on iOS) to manage my investments. It's one of my favourite apps due to its simplicity, and I wanted to replicate the functionality with what I've learnt so far in this CS50P course. The best of which I can do without an interface is a command-line app.


#### Features
The core features of this program are as follows:
- Ability to deposit cash, which will be used to trade
- Ability to withdraw cash
- Ability to look up a stock by ticker and see it's price and trading volume information for the past year
- Ability to record the buying of X number of stocks for a given date
- Ability to record the selling of Y number of stocks for a given date
- Ability to view all past transactions
- Ability to view all past transactions for a given stock
- Ability to view all current holdings and performance metrics (i.e. Realised and Unrealised gains)
- Ability to see how much cash I have in the system

Additionally, the program should handle cases where an action won't make sense / be possible, and warn the user, such as:
- Depositing or withdrawing zero or negative amounts of cash
- Withdrawing more cash than they have in the system
- Looking up a stock by ticker that doesn't exist
- Recording a buy/sell of a stock that doesn't exist
- Recording a buy of a stock when they don't have enough cash in the program
- Selling more shares of a stock that a user has
- Viewing transactions of a stock that a user never had


#### Scope
This program is intended to be quite basic in its functionality (as specified above) and will not include in its scope the following:
- Dividends tracking
- Looking up more information about a stock (i.e. Company description, CEO, Market cap, Financial metrics)
- Returning to the user historic prices of a stock from more than 1 year ago
- Tax accounting calculations (i.e. FIFO, FILO considerations)
- Creating a GUI interface


#### Technology
As this is a final project for CS50P, the project is written in Python. Reasoning for each library used in this project are below.
- *yfinance*: This package contains information from the Yahoo Finance API and has current and historic information. It allows us to get current and historic stock information, specifically "Close price" and "Trading volume", by ticker.
- *psycopg2-binary*: The more development and testing inclined version (dependency-free) of Python's Postgresql database adapter. This will allow us to store cash transactions, stock transactions, holdings and realised delta of the user's stock portfolio. The goal is so the user can open up the app any time and have their historic information available.
- *typer*: A library that simplifies the creation of command-line interface commands and displaying of information back to the user. This is how we will create commands for the user to use in the appy (i.e. deposit and buy)
- *rich*: A library that will make terminal output prettier and more readable. This project uses it to create nice-looking tables and colour columns and text.
- *datetime*: A built-in module that provides classes for working with dates and times. Allows us to find today's date and format date.
- *matplotlib*: A library that allows for creating a wide variety of static, animated, and interactive visualizations with data. This project uses it to output a plot of the "Close price" and "Trading volume" of a given ticker (stock) for the past year, to aid a user in their stock trading decision making.
- *pytest*: CS50's chosen library for testing code in Python. Will be used to test all our functions, including our main class (more on that below) and its functions.


#### Design decisions
The below is a brief description and justification of design decisions made in the code of this project.
- The database for this project will contain 4 tables. All that is needed for the features specified above:
    1. cash_transactions: A record of all cash deposits, withdrawals and transactions that affect a user's cash.
    2. transactions: A record of all stock transactions a user has partaken in (buy / sell).
    3. holdings: A cumulative record of all stocks a user has and/or still holds. Note that a stock will still appear in this table even if a user no longer has any more shares of a stock, but used to (to record historic information).
    4. realised_delta: A record of the realised delta of a user's holdings - i.e. a record of the realised loss/gain of all stocks a user has sold.

    - The database configuration, connection and initialisation have all been abstracted and created as seperate functions to allow for flexibility.


- The "Portfolio" is a class, that when instantiated handles database closing and execution / rollback on its own, at the instance level. It also:
    - Has properties for cash_balance, total_value (of portfolio), realised_delta and unrealised_delta which get called whenever a user requests for the relevant information from the program.
    - Running the project without command will display all the properties, as well as all the user's current holdings.
    - The core portfolio (class) functions are:
        1. update_cash: Which handles depositing and withdrawing a user's cash into the program, as well as inserting into the "cash_transactions" table and error handling.
        2. record_transaction: Which is the core function in this program, handling the logic of BUY/SELL transactions, calling other functions and database table inserting/updating. It calls the following helper functions:
            - _update_holdings_on_buy: Updates holdings table when a "BUY" transaction occurs
            - _validate_sale; Ensures the user has enough shares of the stock they are tryiung to sell
            - _update_holdings_on_sell: Updates holdings table when a "SELL" transaction occurs
            - _get_average_purchase_price: Gets the average purchase price of a user's holding of a stock, to aid in calculation in other functions.
            - _update_cash_on_buy: Updates the cash_transactions table when a "BUY" transaction occurs
            - _update_cash_on_sell: Updates the cash_transactions table when a "SELL" transaction occurs
        3. get_transactions: Returns all transactions of a user's stock portfolio (used in other functions).
        4. get_stock_transactions: Returns all transactions of a user's holdings of a particular stock.
        5. get_holdings: Returns all current holdings of a user (and those that are noew of zero share quantity).

- Using the "Typer" library, a bunch of command_line commands have been created for the user to use. Each of which of course has helper text if the user requests for it with the "--help" command when running the program:
    1. deposit: User specifies the amount of cash to deposit.
    2. withdraw: User specifies the amount of cash to withdraw.
    3. buy: User specifies a ticker and number of shares to buy (Optional arguments: Date, Price).
    4. sell: User specifies a ticker and number of shares to sell (Optional arguments: Date, Price).
    5. all_holdings: User types this to see all of the current holdings, as well as total_value, cash_balance, unrealised_delta and realised_delta (Functionally same as running the program without any commands).
    6. stock_transactions: User specifies a stock by ticker to see all transactions they have had for the stock.
    7. all_transactions: User types this to see all stock transactions they have ever recorded in the program.
    8. stock_info: User specifies a stock by ticker to view the past year information of the stock's "Close price" and "Trading volume" output as a PNG in the project folder.
    - In addition to these app.commands, there are four display functions which handle the rendering and side-effect of presenting the requested data to the user:
        1. display_holdings: Renders and prints a table of the user's current holdings.
        2. display_stock_transactions: Renders and prints a table of the user's transactions of a specified stock.
        3. display_all_transactions: Renders and prints a table of all of the user's historic stock transactions.
        4. display_stock_info: Calls the stock_info function to generate the plot as a PNG in the project folder.
