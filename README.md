# GRITT BANK APPLICATION

**Project Name:** Gritt Bank  
**Project Type:** Banking Application  
**Version:** 1.0  
**Status:** Initial Development  

## 1. Project Overview

Gritt Bank is a digital banking application designed to allow users to perform basic banking transactions conveniently and securely. The application enables customers to register accounts, access their banking information, deposit money, withdraw funds, check their account balances, and manage their account security.

The main objective of Gritt Bank is to provide a simple, user-friendly banking experience where users can manage their finances without necessarily visiting a physical banking institution.

## 2. Core Features and Functionalities

### 2.1 User Registration
- Allow new users to create a bank account.
- Collect essential user information, including:
  - Full name
  - Email address
  - Phone number
  - National ID or identification number
  - Account PIN
- Automatically generate a unique bank account number.
- Validate user information before creating an account.
- Prevent duplicate account registrations.

### 2.2 User Login
- Allow registered users to log into their accounts.
- Authenticate users using their account number and PIN.
- Prevent unauthorized access.
- Provide appropriate error messages for incorrect login credentials.

### 2.3 Check Account Balance
- Allow users to view their current account balance.
- Display the available funds in their accounts.
- Ensure that the balance updates after every successful transaction.

### 2.4 Deposit Money
- Allow users to deposit money into their accounts.
- Request the amount to be deposited.
- Validate that the deposit amount is greater than zero.
- Update the account balance after a successful deposit.
- Generate a transaction confirmation.

### 2.5 Withdraw Money
- Allow users to withdraw money from their accounts.
- Request the withdrawal amount.
- Check whether the account has sufficient funds.
- Prevent withdrawals exceeding the available balance.
- Deduct the withdrawn amount from the account balance.
- Generate a transaction confirmation.

### 2.6 Change Account PIN
- Allow users to change their existing account PIN.
- Require the user to enter their current PIN.
- Request a new PIN and confirmation of the new PIN.
- Validate the new PIN before updating it.
- Ensure that the new PIN is securely stored.

## 3. Additional Recommended Features

To make Gritt Bank more functional and user-friendly, the following features can also be incorporated.

### 3.1 Transaction History
- Display all previous deposits and withdrawals.
- Show transaction dates and times.
- Display transaction types and amounts.
- Show the account balance after each transaction.

### 3.2 Money Transfer
- Allow users to transfer money to other Gritt Bank accounts.
- Require the recipient's account number.
- Validate the recipient's account details.
- Check the sender's available balance.
- Deduct money from the sender and credit the recipient.
- Generate a transfer confirmation.

### 3.3 Account Details
Allow users to view their personal banking information, including:
- Account holder's name.
- Account number.
- Email address.
- Phone number.
- Account creation date.

### 3.4 Forgot PIN
- Allow users who have forgotten their PIN to initiate account recovery.
- Verify their identity before resetting the PIN.
- Allow them to create a new PIN securely.

### 3.5 Logout
- Provide a logout option.
- End the user's active session.
- Require authentication before accessing the account again.

### 3.6 Transaction Limits
- Set minimum and maximum withdrawal amounts.
- Establish daily transaction limits.
- Prevent transactions that exceed the permitted limits.

## 4. Application Workflow

The application should follow this general workflow:

1. The user launches the Gritt Bank application.
2. The application displays the welcome screen.
3. New users select the registration option.
4. Existing users log in using their account number and PIN.
5. After successful authentication, the user accesses the banking dashboard.
6. The dashboard provides options to:
   - Check balance.
   - Deposit money.
   - Withdraw money.
   - Transfer money.
   - View transaction history.
   - Change PIN.
   - View account details.
   - Logout.
7. The system validates every transaction before processing it.
8. The account balance and transaction records are updated accordingly.

## 5. Security Requirements

Since Gritt Bank handles financial transactions and personal information, security should be a major consideration.

The application should:
- Store PINs securely using password hashing.
- Never store account PINs in plain text.
- Validate all user inputs.
- Prevent unauthorized access to accounts.
- Ensure users cannot withdraw more money than they have.
- Maintain transaction records.
- Use secure authentication and session management.
- Prevent unauthorized modification of account balances.

## 6. Business Rules

The application should operate according to the following rules:

1. Every user must have a unique account number.
2. Every registered user must have a valid PIN.
3. Users must authenticate before accessing banking services.
4. Deposits must be greater than zero.
5. Withdrawals must not exceed the available account balance.
6. Money transfers must only be made to valid accounts.
7. Every successful transaction must be recorded.
8. Account balances must never become negative.
9. Users must provide their existing PIN before changing it.
10. Failed transactions must not alter account balances.

## 7. Main Application Modules

| Module | Description |
|---|---|
| Registration | Creates new bank accounts. |
| Authentication | Handles login and account access. |
| Dashboard | Displays banking options and account information. |
| Balance Management | Displays available account balances. |
| Deposit | Processes deposits. |
| Withdrawal | Processes withdrawals. |
| PIN Management | Allows users to change their PINs. |
| Transfers | Enables transfers between accounts. |
| Transaction History | Records and displays account activities. |
| Account Management | Displays and manages customer information. |

## 8. Expected Outcome

At the completion of development, Gritt Bank should provide a functional banking application that allows users to register, authenticate, manage their accounts, and perform basic banking transactions.

The application should prioritize simplicity, accuracy, security, and a user-friendly experience.

## 9. Future Improvements

Possible future enhancements include:

- Integration with M-Pesa for deposits and withdrawals.
- SMS and email transaction notifications.
- Integration with actual banking payment systems.
- Biometric authentication.
- Admin dashboard for managing customer accounts.
- Account statement generation and PDF downloads.
- Interest calculation on savings accounts.
- Support for multiple account types, such as savings and current accounts.

## 10. Disclaimer

Gritt Bank is a software development project intended to demonstrate basic banking operations and account management. Unless connected to licensed banking infrastructure and appropriate financial services, the application should operate as a simulation and should not be used to process actual customer funds.