import sqlite3
import os
from datetime import datetime, timedelta

class DatabaseManager:
    def __init__(self, db_name='financial_tracker.db'):
        self.db_name = db_name
        self.create_tables()
        self.populate_initial_data()

    def get_connection(self):
        """Create and return a database connection"""
        return sqlite3.connect(self.db_name)

    def create_tables(self):
        """Create necessary tables for the financial tracker"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Users Table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                email TEXT UNIQUE,
                total_balance REAL DEFAULT 0
            )
            ''')

            # Transactions Table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL NOT NULL,
                type TEXT NOT NULL,
                category TEXT,
                description TEXT,
                date DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            ''')

            # Savings Goals Table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS savings_goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                name TEXT NOT NULL,
                target_amount REAL NOT NULL,
                current_amount REAL DEFAULT 0,
                target_date DATE,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            ''')

            conn.commit()

    def populate_initial_data(self):
        """Populate database with some initial dummy data"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Check if data already exists
            cursor.execute('SELECT COUNT(*) FROM users')
            if cursor.fetchone()[0] > 0:
                return

            # Insert dummy users
            users = [
                ('johndoe', 'password123', 'john.doe@example.com', 5000),
                ('janedoe', 'password456', 'jane.doe@example.com', 7500)
            ]
            cursor.executemany('''
                INSERT INTO users (username, password, email, total_balance) 
                VALUES (?, ?, ?, ?)
            ''', users)
            
            # Get user IDs
            cursor.execute('SELECT id FROM users')
            user_ids = [row[0] for row in cursor.fetchall()]

            # Insert dummy transactions
            transactions = []
            for user_id in user_ids:
                dummy_transactions = [
                    (user_id, 2000, 'income', 'Salary', 'Monthly salary', 
                     (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')),
                    (user_id, 500, 'expense', 'Groceries', 'Monthly grocery shopping', 
                     (datetime.now() - timedelta(days=25)).strftime('%Y-%m-%d %H:%M:%S')),
                    (user_id, 1000, 'income', 'Freelance', 'Side project income', 
                     (datetime.now() - timedelta(days=20)).strftime('%Y-%m-%d %H:%M:%S')),
                    (user_id, 300, 'expense', 'Utilities', 'Electricity bill', 
                     (datetime.now() - timedelta(days=15)).strftime('%Y-%m-%d %H:%M:%S'))
                ]
                transactions.extend(dummy_transactions)

            cursor.executemany('''
                INSERT INTO transactions 
                (user_id, amount, type, category, description, date) 
                VALUES (?, ?, ?, ?, ?, ?)
            ''', transactions)

            # Insert dummy savings goals
            savings_goals = [
                (user_ids[0], 'Emergency Fund', 10000, 2500, '2024-12-31'),
                (user_ids[1], 'Vacation', 5000, 1000, '2024-09-30')
            ]
            cursor.executemany('''
                INSERT INTO savings_goals 
                (user_id, name, target_amount, current_amount, target_date) 
                VALUES (?, ?, ?, ?, ?)
            ''', savings_goals)

            conn.commit()

# Create database and populate initial data
db_manager = DatabaseManager()