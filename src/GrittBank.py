import random
import re


# ---------------------------------------------------------------------------
# Validation helpers (each returns an error message, or None if the value is OK)
# ---------------------------------------------------------------------------

def validate_full_name(name):
    name = name.strip()
    if len(name.split()) < 2:
        return "Full name must include at least a first and last name."
    if not re.fullmatch(r"[A-Za-z][A-Za-z\s'\-]*", name):
        return "Full name can only contain letters, spaces, hyphens and apostrophes."
    return None


def validate_email(email):
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email.strip()):
        return "Email address is not valid."
    return None


def normalize_phone(phone):
    """Strip spaces, dashes and brackets so numbers compare consistently."""
    return re.sub(r"[\s\-()]", "", phone.strip())


def validate_phone(phone):
    if not re.fullmatch(r"\+?\d{10,15}", normalize_phone(phone)):
        return "Phone number must have 10-15 digits (a leading + is allowed)."
    return None


def validate_national_id(national_id):
    if not re.fullmatch(r"[A-Za-z0-9]{6,12}", national_id.strip()):
        return "National ID must be 6-12 letters or digits."
    return None


def validate_pin(pin):
    if not (pin.isdigit() and len(pin) == 4):
        return "PIN must be exactly 4 digits."
    return None


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------

class Account:
    def __init__(self, account_number, full_name, email, phone, national_id, pin, balance=0):
        self.account_number = account_number
        self.full_name = full_name
        self.email = email
        self.phone = phone
        self.national_id = national_id
        self.pin = pin
        self.balance = balance

    def check_pin(self, pin):
        """Returns True if the pin matches."""
        return self.pin == pin

    def deposit(self, amount):
        """Rejects amounts <= 0, otherwise adds to balance."""
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
        if validate_pin(new_pin) is not None:
            return False
        self.pin = new_pin
        return True


# ---------------------------------------------------------------------------
# Bank (stores accounts and handles registration)
# ---------------------------------------------------------------------------

class Bank:
    def __init__(self):
        self.accounts = {}  # account_number -> Account

    def generate_account_number(self):
        """Generate a unique 10-digit account number."""
        while True:
            number = "".join(random.choices("0123456789", k=10))
            if number not in self.accounts:
                return number

    def find_duplicate(self, email, phone, national_id):
        """Return a message describing the first duplicate found, or None."""
        email = email.strip().lower()
        phone = normalize_phone(phone)
        national_id = national_id.strip().upper()
        for acc in self.accounts.values():
            if acc.email == email:
                return "An account with this email address already exists."
            if acc.phone == phone:
                return "An account with this phone number already exists."
            if acc.national_id == national_id:
                return "An account with this National ID already exists."
        return None

    def register(self, full_name, email, phone, national_id, pin):
        """
        Validate the details and create an account.
        Returns (account, errors). On failure account is None.
        """
        errors = [
            e for e in (
                validate_full_name(full_name),
                validate_email(email),
                validate_phone(phone),
                validate_national_id(national_id),
                validate_pin(pin),
            ) if e
        ]
        if errors:
            return None, errors

        duplicate = self.find_duplicate(email, phone, national_id)
        if duplicate:
            return None, [duplicate]

        account = Account(
            account_number=self.generate_account_number(),
            full_name=" ".join(full_name.split()),
            email=email.strip().lower(),
            phone=normalize_phone(phone),
            national_id=national_id.strip().upper(),
            pin=pin,
        )
        self.accounts[account.account_number] = account
        return account, []

    def get_account(self, account_number):
        return self.accounts.get(account_number)


# ---------------------------------------------------------------------------
# User interface
# ---------------------------------------------------------------------------

def show_start_menu():
    print("\nWelcome to Gritt Bank")
    print("\n1. Register")
    print("2. Login")
    print("3. Exit")


def show_menu():
    print("\n1. Check Balance")
    print("2. Deposit")
    print("3. Withdraw")
    print("4. Change PIN")
    print("5. Logout")


def ask_valid(prompt, validator):
    """Keep asking until the validator accepts the input."""
    while True:
        value = input(prompt)
        error = validator(value)
        if error is None:
            return value
        print(error)


def register_user(bank):
    print("\n--- New Account Registration ---")
    full_name = ask_valid("Full name: ", validate_full_name)
    email = ask_valid("Email address: ", validate_email)
    phone = ask_valid("Phone number: ", validate_phone)
    national_id = ask_valid("National ID / identification number: ", validate_national_id)
    pin = ask_valid("Choose a 4-digit PIN: ", validate_pin)

    account, errors = bank.register(full_name, email, phone, national_id, pin)
    if account is None:
        print("\nRegistration failed:")
        for error in errors:
            print(f" - {error}")
        return

    print("\nRegistration successful!")
    print(f"Welcome, {account.full_name}.")
    print(f"Your account number is: {account.account_number}")
    print("Keep it safe - you will need it to log in.")


def login(bank):
    """Return the logged-in Account, or None after 3 failed attempts."""
    for attempt in range(3):
        number = input("Account number: ").strip()
        pin = input("Enter your PIN: ")
        account = bank.get_account(number)
        if account and account.check_pin(pin):
            print(f"Login successful! Hello, {account.full_name}.")
            return account
        print(f"Invalid account number or PIN. {2 - attempt} attempts left.")
    return None


def get_amount(prompt):
    """Ask for a number; return None if the input isn't valid."""
    try:
        return float(input(prompt))
    except ValueError:
        print("Please enter a valid number.")
        return None


def account_session(account):
    while True:
        show_menu()
        choice = input("Choose an option: ")

        if choice == "1":
            print(f"Your balance is ${account.get_balance():.2f}")
        elif choice == "2":
            amount = get_amount("Amount to deposit: ")
            if amount is not None:
                if account.deposit(amount):
                    print(f"Deposited ${amount:.2f}.")
                else:
                    print("Invalid deposit amount.")
        elif choice == "3":
            amount = get_amount("Amount to withdraw: ")
            if amount is not None:
                if account.withdraw(amount):
                    print(f"Withdrew ${amount:.2f}.")
                else:
                    print("Invalid amount or insufficient funds.")
        elif choice == "4":
            old_pin = input("Enter current PIN: ")
            new_pin = input("Enter new 4-digit PIN: ")
            if account.change_pin(old_pin, new_pin):
                print("PIN changed successfully.")
            else:
                print("PIN change failed. Check your current PIN and make sure the new one is 4 digits.")
        elif choice == "5":
            print("Logged out.")
            break
        else:
            print("Invalid option.")


def main():
    bank = Bank()

    while True:
        show_start_menu()
        choice = input("Choose an option: ")

        if choice == "1":
            register_user(bank)
        elif choice == "2":
            account = login(bank)
            if account is None:
                print("Too many failed attempts.")
            else:
                account_session(account)
        elif choice == "3":
            print("Goodbye!")
            break
        else:
            print("Invalid option.")


if __name__ == "__main__":
    main()