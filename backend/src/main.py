import asyncio
import random
import resemble.std.collections.sorted_map
import resemble.thirdparty.mailgun
import uuid
from bank.v1.bank_rsm import (
    Account,
    AccountBalancesRequest,
    AccountBalancesResponse,
    Balance,
    BalanceRequest,
    BalanceResponse,
    Bank,
    DepositRequest,
    DepositResponse,
    InterestTaskRequest,
    InterestTaskResponse,
    OpenRequest,
    OpenResponse,
    OverdraftError,
    SignUpRequest,
    SignUpResponse,
    TransferRequest,
    TransferResponse,
    WithdrawRequest,
    WithdrawResponse,
)
from datetime import timedelta
from resemble.aio.applications import Application
from resemble.aio.call import Options
from resemble.aio.contexts import (
    ReaderContext,
    TransactionContext,
    WriterContext,
)
from resemble.aio.secrets import Secrets
from resemble.std.collections.v1.sorted_map_rsm import SortedMap
from resemble.thirdparty.mailgun import MAILGUN_API_KEY_SECRET_NAME
from resemble.thirdparty.mailgun.v1 import mailgun_rsm as mailgun
from uuid_extensions import uuid7


class AccountServicer(Account.Interface):

    async def Balance(
        self,
        context: ReaderContext,
        state: Account.State,
        request: BalanceRequest,
    ) -> BalanceResponse:
        return BalanceResponse(amount=state.balance)

    async def Deposit(
        self,
        context: WriterContext,
        state: Account.State,
        request: DepositRequest,
    ) -> DepositResponse:
        state.balance += request.amount
        return DepositResponse()

    async def Withdraw(
        self,
        context: WriterContext,
        state: Account.State,
        request: WithdrawRequest,
    ) -> WithdrawResponse:
        state.balance -= request.amount
        if state.balance < 0:
            raise Account.WithdrawAborted(
                OverdraftError(amount=-state.balance)
            )
        return WithdrawResponse()

    async def Open(
        self,
        context: WriterContext,
        state: Account.State,
        request: OpenRequest,
    ) -> OpenResponse:
        await self.lookup().schedule(
            when=timedelta(seconds=1),
        ).InterestTask(context)

        return OpenResponse()

    async def InterestTask(
        self,
        context: WriterContext,
        state: Account.State,
        request: InterestTaskRequest,
    ) -> InterestTaskResponse:
        state.balance += 1

        await self.lookup().schedule(
            when=timedelta(seconds=random.randint(1, 4))
        ).InterestTask(context)

        return InterestTaskResponse()


class BankServicer(Bank.Interface):

    def __init__(self):
        self.html_email = open('backend/src/email_to_bank_users.html').read()
        self.text_email = open('backend/src/email_to_bank_users.txt').read()

    async def AccountBalances(
        self,
        context: ReaderContext,
        state: Bank.State,
        request: AccountBalancesRequest,
    ) -> AccountBalancesResponse:
        # Get the first "page" of account IDs (32 entries).
        account_ids_map = SortedMap.lookup(state.account_ids_map_id)
        account_ids = await account_ids_map.Range(context, limit=32)

        async def balance(account_id: str):
            account = Account.lookup(account_id)
            balance = await account.Balance(context)
            return Balance(account_id=account_id, balance=balance.amount)

        return AccountBalancesResponse(
            balances=await asyncio.gather(
                *[
                    balance(account_id.value.decode())
                    for account_id in account_ids.entries
                ]
            )
        )

    async def SignUp(
        self,
        context: TransactionContext,
        state: Bank.State,
        request: SignUpRequest,
    ) -> SignUpResponse:
        account_id = request.account_id

        mailgun_api_key = await Secrets().get(MAILGUN_API_KEY_SECRET_NAME)

        await mailgun.Message.construct().Send(
            context,
            Options(bearer_token=mailgun_api_key.decode()),
            recipient=account_id,
            sender='team@reboot.dev',
            domain='reboot.dev',
            subject='Thanks for your time!',
            html=self.html_email,
            text=self.text_email,
        )

        account, _ = await Account.construct(id=account_id).Open(context)

        await account.Deposit(context, amount=request.initial_deposit)

        if state.account_ids_map_id == '':
            state.account_ids_map_id = str(uuid.uuid4())

        # Save the account ID to our _distributed_ map using a UUIDv7
        # to get a "timestamp" based ordering.
        await SortedMap.lookup(state.account_ids_map_id).Insert(
            context,
            entries={str(uuid7()): account_id.encode()},
        )

        return SignUpResponse()

    async def Transfer(
        self,
        context: TransactionContext,
        state: Bank.State,
        request: TransferRequest,
    ) -> TransferResponse:
        from_account = Account.lookup(request.from_account_id)
        to_account = Account.lookup(request.to_account_id)

        await asyncio.gather(
            from_account.Withdraw(context, amount=request.amount),
            to_account.Deposit(context, amount=request.amount),
        )

        return TransferResponse()


async def main():
    await Application(
        servicers=[AccountServicer, BankServicer] +
        # Include mailgun `Message` servicers.
        resemble.thirdparty.mailgun.servicers() +
        # Include `SortedMap` servicers.
        resemble.std.collections.sorted_map.servicers(),
    ).run()


if __name__ == '__main__':
    asyncio.run(main())
