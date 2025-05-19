from flask import Flask, request, jsonify, send_file
import sqlite3
import os
from database import DatabaseManager
from datetime import datetime, timedelta
import pandas as pd
import matplotlib.pyplot as plt
import io
import seaborn as sns
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas

from flask_cors import CORS

app = Flask(__name__)
CORS(app)
db_manager = DatabaseManager()

def dict_factory(cursor, row):
    """Convert sqlite3 row to dictionary"""
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

@app.route('/')
def serve_frontend():
    return send_file('index.html')

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    email = data.get('email', '')

    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
            if cursor.fetchone():
                return jsonify({"error": "Username already exists"}), 400

            cursor.execute('''
                INSERT INTO users (username, password, email, total_balance) 
                VALUES (?, ?, ?, 0)
            ''', (username, password, email))
            conn.commit()

        return jsonify({"message": "Registration successful"}), 200
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 500

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    try:
        with db_manager.get_connection() as conn:
            conn.row_factory = dict_factory
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM users WHERE username = ? AND password = ?', 
                         (username, password))
            user = cursor.fetchone()

            if user:
                return jsonify({
                    "message": "Login successful", 
                    "user": {
                        "username": user['username'],
                        "balance": user['total_balance']
                    }
                }), 200
            else:
                return jsonify({"error": "Invalid credentials"}), 401
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 500

@app.route('/add_transaction', methods=['POST'])
def add_transaction():
    data = request.json
    username = data.get('username')
    amount = data.get('amount')
    transaction_type = data.get('type')  # 'income' or 'expense'
    category = data.get('category', '')
    description = data.get('description', '')
    date = data.get('date', datetime.now().strftime('%Y-%m-%d'))  # Optional date parameter

    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get user ID and current balance
            cursor.execute('SELECT id, total_balance FROM users WHERE username = ?', (username,))
            user = cursor.fetchone()
            
            if not user:
                return jsonify({"error": "User not found"}), 404

            user_id, current_balance = user

            # Check if expense exceeds balance
            if transaction_type == 'expense' and amount > current_balance:
                return jsonify({"error": "Insufficient balance"}), 400

            # Insert transaction
            cursor.execute('''
                INSERT INTO transactions 
                (user_id, amount, type, category, description, date) 
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, amount, transaction_type, category, description, date))

            # Update user balance
            new_balance = current_balance + amount if transaction_type == 'income' else current_balance - amount
            cursor.execute('UPDATE users SET total_balance = ? WHERE id = ?', 
                         (new_balance, user_id))

            conn.commit()

            # Check if any savings goals are linked to this category
            if transaction_type == 'income':
                cursor.execute('''
                    SELECT * FROM savings_goals 
                    WHERE user_id = ? AND category = ? AND current_amount < target_amount
                ''', (user_id, category))
                savings_goal = cursor.fetchone()
                
                if savings_goal:
                    # Calculate amount to save (e.g., 10% of income)
                    saving_amount = min(amount * 0.1, 
                                     savings_goal[3] - savings_goal[2])  # target_amount - current_amount
                    
                    cursor.execute('''
                        UPDATE savings_goals 
                        SET current_amount = current_amount + ? 
                        WHERE id = ?
                    ''', (saving_amount, savings_goal[0]))
                    
                    conn.commit()

        return jsonify({
            "message": "Transaction added successfully",
            "new_balance": new_balance
        }), 200
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get_transactions', methods=['GET'])
def get_transactions():
    username = request.args.get('username')
    days = int(request.args.get('days', 90))  # Default to 90 days
    category = request.args.get('category')  # Optional category filter
    transaction_type = request.args.get('type')  # Optional type filter
    
    try:
        with db_manager.get_connection() as conn:
            conn.row_factory = dict_factory
            cursor = conn.cursor()
            
            cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
            user = cursor.fetchone()
            
            if not user:
                return jsonify({"error": "User not found"}), 404

            date_limit = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            query = '''
                SELECT * FROM transactions 
                WHERE user_id = ? AND date >= ?
            '''
            params = [user['id'], date_limit]

            if category:
                query += ' AND category = ?'
                params.append(category)
            
            if transaction_type:
                query += ' AND type = ?'
                params.append(transaction_type)

            query += ' ORDER BY date DESC'
            
            cursor.execute(query, params)
            transactions = cursor.fetchall()

            # Calculate summary statistics
            total_income = sum(t['amount'] for t in transactions if t['type'] == 'income')
            total_expenses = sum(t['amount'] for t in transactions if t['type'] == 'expense')
            
            return jsonify({
                "transactions": transactions,
                "summary": {
                    "total_income": total_income,
                    "total_expenses": total_expenses,
                    "net_savings": total_income - total_expenses,
                    "period_days": days
                }
            }), 200
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 500

@app.route('/add_savings_goal', methods=['POST'])
def add_savings_goal():
    data = request.json
    username = data.get('username')
    name = data.get('name')
    # category = data.get('category')
    target_amount = data.get('target_amount')
    target_date = data.get('target_date')
    initial_amount = data.get('initial_amount', 0)
    monthly_contribution = data.get('monthly_contribution', 0)

    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
            user = cursor.fetchone()
            
            if not user:
                return jsonify({"error": "User not found"}), 404

            # Check if goal name already exists for user
            cursor.execute('''
                SELECT * FROM savings_goals 
                WHERE user_id = ? AND name = ?
            ''', (user[0], name))
            
            if cursor.fetchone():
                return jsonify({"error": "Savings goal with this name already exists"}), 400

            cursor.execute('''
                INSERT INTO savings_goals 
                (user_id, name, target_amount, current_amount, target_date) 
                VALUES (?, ?, ?, ?, ?)
            ''', (user[0], name, target_amount, initial_amount, 
                  target_date))

            conn.commit()

            return jsonify({
                "message": "Savings goal added successfully",
                "goal": {
                    "name": name,
                    "target_amount": target_amount,
                    "current_amount": initial_amount,
                    "target_date": target_date                }
            }), 200
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get_savings_goals', methods=['GET'])
def get_savings_goals():
    username = request.args.get('username')
    include_completed = request.args.get('include_completed', 'false').lower() == 'true'

    try:
        with db_manager.get_connection() as conn:
            conn.row_factory = dict_factory
            cursor = conn.cursor()
            
            cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
            user = cursor.fetchone()
            
            if not user:
                return jsonify({"error": "User not found"}), 404

            query = '''
                SELECT 
                    sg.*,
                    (sg.target_amount - sg.current_amount) as remaining_amount,
                    CASE 
                        WHEN sg.target_date IS NOT NULL 
                        THEN ROUND(
                            (julianday(sg.target_date) - julianday('now')) / 30.0, 1
                        )
                        ELSE NULL 
                    END as months_remaining,
                    CASE 
                        WHEN sg.target_amount <= sg.current_amount THEN 'Completed'
                        WHEN sg.target_date < date('now') THEN 'Overdue'
                        ELSE 'In Progress'
                    END as status
                FROM savings_goals sg
                WHERE sg.user_id = ?
            '''
            
            if not include_completed:
                query += ' AND sg.current_amount < sg.target_amount'
            
            cursor.execute(query, (user['id'],))
            goals = cursor.fetchall()

            # Calculate additional metrics for each goal
            for goal in goals:
                if goal['months_remaining'] and goal['months_remaining'] > 0:
                    goal['required_monthly_saving'] = (
                        goal['remaining_amount'] / goal['months_remaining']
                    )
                goal['progress_percentage'] = (
                    (goal['current_amount'] / goal['target_amount']) * 100
                    if goal['target_amount'] > 0 else 0
                )

            return jsonify({
                "savings_goals": goals,
                "summary": {
                    "total_goals": len(goals),
                    "completed_goals": sum(1 for g in goals if g['status'] == 'Completed'),
                    "total_saved": sum(g['current_amount'] for g in goals),
                    "total_target": sum(g['target_amount'] for g in goals)
                }
            }), 200
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 500

@app.route('/update_savings_goal', methods=['PUT'])
def update_savings_goal():
    data = request.json
    username = data.get('username')
    goal_id = data.get('goal_id')
    amount = data.get('amount')  # Amount to add or subtract
    operation = data.get('operation', 'add')  # 'add' or 'subtract'

    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            # Verify user and goal
            cursor.execute('''
                SELECT sg.* FROM savings_goals sg
                JOIN users u ON u.id = sg.user_id
                WHERE u.username = ? AND sg.id = ?
            ''', (username, goal_id))
            
            goal = cursor.fetchone()
            if not goal:
                return jsonify({"error": "Savings goal not found"}), 404

            # Update the goal amount
            new_amount = (
                goal[4] + amount if operation == 'add' 
                else goal[4] - amount
            )  # current_amount is at index 4
            
            if new_amount < 0:
                return jsonify({"error": "Cannot reduce below zero"}), 400

            cursor.execute('''
                UPDATE savings_goals 
                SET current_amount = ?
                WHERE id = ?
            ''', (new_amount, goal_id))

            conn.commit()

            return jsonify({
                "message": "Savings goal updated successfully",
                "new_amount": new_amount
            }), 200
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 500

# New endpoint for category-wise expense distribution (pie chart)
@app.route('/visualize/category_distribution', methods=['GET'])
def category_distribution():
    username = request.args.get('username')
    days = int(request.args.get('days', 90))

    try:
        with db_manager.get_connection() as conn:
            conn.row_factory = dict_factory
            cursor = conn.cursor()
            
            cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
            user = cursor.fetchone()
            
            if not user:
                return jsonify({"error": "User not found"}), 404

            date_limit = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            cursor.execute('''
                SELECT category, SUM(amount) as total_amount 
                FROM transactions 
                WHERE user_id = ? AND date >= ? AND type = 'expense'
                GROUP BY category
            ''', (user['id'], date_limit))
            
            data = cursor.fetchall()
            
            # Create pie chart
            plt.figure(figsize=(10, 8))
            plt.pie([row['total_amount'] for row in data], 
                   labels=[row['category'] for row in data],
                   autopct='%1.1f%%')
            plt.title(f'Expense Distribution by Category (Last {days} days)')
            
            # Save plot to bytes buffer
            buf = io.BytesIO()
            plt.savefig(buf, format='png')
            buf.seek(0)
            plt.close()
            
            return send_file(buf, mimetype='image/png')
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 500

# Monthly spending trends (line chart)
@app.route('/visualize/monthly_trends', methods=['GET'])
def monthly_trends():
    username = request.args.get('username')
    days = int(request.args.get('days', 90))

    try:
        with db_manager.get_connection() as conn:
            conn.row_factory = dict_factory
            cursor = conn.cursor()
            
            cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
            user = cursor.fetchone()
            
            if not user:
                return jsonify({"error": "User not found"}), 404

            date_limit = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            cursor.execute('''
                SELECT strftime('%Y-%m', date) as month, 
                       SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END) as expenses,
                       SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END) as income
                FROM transactions 
                WHERE user_id = ? AND date >= ?
                GROUP BY month
                ORDER BY month
            ''', (user['id'], date_limit))
            
            data = cursor.fetchall()
            
            # Create line chart
            plt.figure(figsize=(12, 6))
            months = [row['month'] for row in data]
            plt.plot(months, [row['expenses'] for row in data], label='Expenses', marker='o')
            plt.plot(months, [row['income'] for row in data], label='Income', marker='o')
            plt.title('Monthly Income vs Expenses')
            plt.xlabel('Month')
            plt.ylabel('Amount')
            plt.xticks(rotation=45)
            plt.legend()
            plt.grid(True)
            
            buf = io.BytesIO()
            plt.savefig(buf, format='png')
            buf.seek(0)
            plt.close()
            
            return send_file(buf, mimetype='image/png')
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 500

# Savings goals progress (bar chart)
@app.route('/visualize/savings_progress', methods=['GET'])
def savings_progress():
    username = request.args.get('username')

    try:
        with db_manager.get_connection() as conn:
            conn.row_factory = dict_factory
            cursor = conn.cursor()
            
            cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
            user = cursor.fetchone()
            
            if not user:
                return jsonify({"error": "User not found"}), 404

            cursor.execute('''
                SELECT name, current_amount, target_amount
                FROM savings_goals 
                WHERE user_id = ?
            ''', (user['id'],))
            
            data = cursor.fetchall()
            
            # Create bar chart
            plt.figure(figsize=(10, 6))
            goals = [row['name'] for row in data]
            current = [row['current_amount'] for row in data]
            target = [row['target_amount'] for row in data]
            
            x = range(len(goals))
            width = 0.35
            
            plt.bar(x, current, width, label='Current Amount')
            plt.bar([i + width for i in x], target, width, label='Target Amount')
            
            plt.xlabel('Savings Goals')
            plt.ylabel('Amount')
            plt.title('Savings Goals Progress')
            plt.xticks([i + width/2 for i in x], goals, rotation=45)
            plt.legend()
            
            buf = io.BytesIO()
            plt.savefig(buf, format='png')
            buf.seek(0)
            plt.close()
            
            return send_file(buf, mimetype='image/png')
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 500

# Weekly budget tracking (stacked bar chart)
@app.route('/visualize/weekly_budget', methods=['GET'])
def weekly_budget():
    username = request.args.get('username')
    weeks = int(request.args.get('weeks', 4))  # Default to last 4 weeks

    try:
        with db_manager.get_connection() as conn:
            conn.row_factory = dict_factory
            cursor = conn.cursor()
            
            cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
            user = cursor.fetchone()
            
            if not user:
                return jsonify({"error": "User not found"}), 404

            date_limit = (datetime.now() - timedelta(weeks=weeks)).strftime('%Y-%m-%d')
            
            cursor.execute('''
                SELECT strftime('%W', date) as week,
                       category,
                       SUM(amount) as total_amount
                FROM transactions 
                WHERE user_id = ? AND date >= ? AND type = 'expense'
                GROUP BY week, category
                ORDER BY week
            ''', (user['id'], date_limit))
            
            data = cursor.fetchall()
            
            # Process data for stacked bar chart
            df = pd.DataFrame(data)
            pivot_data = df.pivot(index='week', columns='category', values='total_amount').fillna(0)
            
            # Create stacked bar chart
            ax = pivot_data.plot(kind='bar', stacked=True, figsize=(12, 6))
            plt.title('Weekly Expenses by Category')
            plt.xlabel('Week Number')
            plt.ylabel('Amount')
            plt.legend(title='Categories', bbox_to_anchor=(1.05, 1), loc='upper left')
            plt.tight_layout()
            
            buf = io.BytesIO()
            plt.savefig(buf, format='png')
            buf.seek(0)
            plt.close()
            
            return send_file(buf, mimetype='image/png')
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)