"""Gritt Bank - simple console banking app"""


class Account:
    def __init__(self, owner, pin, balance=0):
        self.owner = owner
        self.pin = pin
        self.balance = balance

    def check_pin(self, pin):
        """Returns True if the pin matches."""
        return self.pin == pin

    def deposit(self, amount):
        """Rejects amounts <= 0, otherwise adds to the balance."""
        if amount <= 0:
            return False
        self.balance += amount
        return True

    def withdraw(self, amount):
        """Rejects amounts <= 0 or > balance, otherwise subtracts."""
        if amount <= 0 or amount > self.balance:
            return False
        self.balance -= amount
        return True

    def get_balance(self):
        return self.balance

    def change_pin(self, old_pin, new_pin):
        """Verify old pin first, then validate and set new_pin."""
        if not self.check_pin(old_pin):
            return False
        if not (new_pin.isdigit() and len(new_pin) == 4):
            return False
        self.pin = new_pin
        return True


def show_menu():
    print("\nWelcome to Gritt Bank")
    print("\n1. Check Balance")
    print("2. Deposit")
    print("3. Withdraw")
    print("4. Change PIN")
    print("5. Logout")


def login(account):
    for attempt in range(3):
        pin = input("Enter your PIN: ")
        if account.check_pin(pin):
            print("Login successful!")
            return True
        print(f"Incorrect PIN. {2 - attempt} attempts left.")
    return False  # only after all 3 attempts have failed


def ask_amount(prompt):
    """Returns a float, or None if the input isn't a number."""
    try:
        return float(input(prompt))
    except ValueError:
        print("Please enter a valid number.")
        return None


def main():
    account = Account("Alex", pin="1234", balance=500)

    if not login(account):
        print("Too many failed attempts.")
        return

    while True:
        show_menu()
        choice = input("Choose an option: ")

        if choice == "1":
            print(f"Your balance is: {account.get_balance():.2f}")
        elif choice == "2":
            amount = ask_amount("Enter amount to deposit: ")
            if amount is not None:
                if account.deposit(amount):
                    print(f"Deposited {amount:.2f}. New balance: {account.get_balance():.2f}")
                else:
                    print("Invalid amount. Must be greater than 0.")
        elif choice == "3":
            amount = ask_amount("Enter amount to withdraw: ")
            if amount is not None:
                if account.withdraw(amount):
                    print(f"Withdrew {amount:.2f}. New balance: {account.get_balance():.2f}")
                else:
                    print("Invalid amount or insufficient funds.")
        elif choice == "4":
            old_pin = input("Enter old PIN: ")
            new_pin = input("Enter new PIN (4 digits): ")
            if account.change_pin(old_pin, new_pin):
                print("PIN changed successfully.")
            else:
                print("PIN change failed. Check your old PIN and that the new one is 4 digits.")
        elif choice == "5":
            print("Goodbye!")
            break
        else:
            print("Invalid option.")

        input("\nPress Enter to continue...")


if __name__ == "__main__":
    main()
