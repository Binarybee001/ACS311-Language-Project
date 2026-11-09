"""Benjamin's code"""

class Account:
    def __init__(self, owner, pin, balance=0):
        self.owner = owner
        self.pin = pin
        self.balance = balance

    def check_pin(self, pin):
        """Returns true if the pin matches"""
        return self.pin == pin

    def deposit(self, amount):
        """Rejects amounts <= 0 or > balance, otherwise subtract."""
        pass

    def get_balance(self):
        return self.balance

    def change_pin(self,old_pin,new_pin):
        """Verify old pin first, then validates and set new_pin."""
        pass



def show_menu():
    print("\nWelcome to Gritt Bank")
    print("\n1. Check Balance")
    print("2. Deposit")
    print("3. Withdraw")
    print("4. Change PIN")
    print("5. Logout")

def main():
     account = Account("Alex", pin="1234", balance=500)

def login(account):
    for attempt in range(3):
        pin = input("Enter your PIN: ")
        if account.check_pin(pin):
            print("Login successful!")
            return True
        else:
            print(f"Incorrect PIN. {2-attempt} attempts left.")
        return False
    if not login(account):
        print("Too many failed attempts.")
        return

    while True:
        show_menu()
        choice = input("Choose an option: ")

        if choice == "1":
            pass  # print balance
        elif choice == "2":
            pass  # ask amount, call deposit
        elif choice == "3":
            pass  # ask amount, call withdraw
        elif choice == "4":
            pass  # ask old pin, new pin, call change_pin
        elif choice == "5":
            print("Goodbye!")
            break
        else:
            print("Invalid option.")


if __name__ == "__main__":
    main()