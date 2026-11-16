from datetime import datetime

def check_balance(balance):
    print("\n--- GRITT BANK: ACCOUNT BALANCE ---")
    print(f"Current balance: ${balance:.2f}")


def bank_statement(transactions):
    print("\n--- GRITT BANK: BANK STATEMENT ---")

    if not transactions:
        print("No transactions available.")
        return

    print(f"{'Date':<22} {'Type':<15} {'Amount':<12} {'Balance':<12}")
    print("-" * 65)

    for transaction in transactions:
        print(
            f"{transaction['date']:<22} "
            f"{transaction['type']:<15} "
            f"${transaction['amount']:<11.2f} "
            f"${transaction['balance']:<11.2f}"
        )


def record_transaction(transactions, transaction_type, amount, balance):
    transaction = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type": transaction_type,
        "amount": amount,
        "balance": balance
    }

    transactions.append(transaction)