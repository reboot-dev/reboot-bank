import asyncio
import random
import reboot.std.collections.sorted_map
import reboot.thirdparty.mailgun
import uuid
from bank.v1.bank_rbt import (
    Account,
    AccountBalancesRequest,
    AccountBalancesResponse,
    Balance,
    BalanceRequest,
    BalanceResponse,
    Bank,
    CreateRequest,
    CreateResponse,
    DepositRequest,
    DepositResponse,
    InterestRequest,
    InterestResponse,
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
from log.log import get_logger
from rbt.std.collections.v1.sorted_map_rbt import SortedMap
from rbt.thirdparty.mailgun.v1 import mailgun_rbt as mailgun
from reboot.aio.applications import Application
from reboot.aio.auth.authorizers import allow
from reboot.aio.call import Options
from reboot.aio.contexts import (
    ReaderContext,
    TransactionContext,
    WriterContext,
)
from reboot.aio.external import ExternalContext
from reboot.aio.secrets import SecretNotFoundException, Secrets
from reboot.thirdparty.mailgun import MAILGUN_API_KEY_SECRET_NAME
from typing import Optional
from uuid_extensions import uuid7

logger = get_logger(__name__)

SINGLETON_BANK_ID = 'SVB'


class AccountServicer(Account.Servicer):

    def authorizer(self):
        return allow()

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
        await self.ref().schedule(
            when=timedelta(seconds=1),
        ).Interest(context)

        return OpenResponse()

    async def Interest(
        self,
        context: WriterContext,
        state: Account.State,
        request: InterestRequest,
    ) -> InterestResponse:

        state.balance += 1

        await self.ref().schedule(
            when=timedelta(seconds=random.randint(1, 4))
        ).Interest(context)

        return InterestResponse()


class BankServicer(Bank.Servicer):

    def __init__(self):
        self._html_email = open('backend/src/email_to_bank_users.html').read()
        self._text_email = open('backend/src/email_to_bank_users.txt').read()
        self._secrets = Secrets()

    def authorizer(self):
        return allow()

    async def Create(
        self,
        context: TransactionContext,
        state: Bank.State,
        request: CreateRequest,
    ) -> CreateResponse:
        state.account_ids_map_id = str(uuid.uuid4())

        await SortedMap.ref(state.account_ids_map_id).Insert(
            context,
            entries={},
        )

        return CreateResponse()

    async def AccountBalances(
        self,
        context: ReaderContext,
        state: Bank.State,
        request: AccountBalancesRequest,
    ) -> AccountBalancesResponse:
        # Get the first "page" of account IDs (32 entries).
        account_ids_map = SortedMap.ref(state.account_ids_map_id)
        account_ids = await account_ids_map.Range(context, limit=32)

        async def balance(account_id: str):
            account = Account.ref(account_id)
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

        if mailgun_api_key := await self._mailgun_api_key():
            await mailgun.Message.Send(
                context,
                None,
                Options(bearer_token=mailgun_api_key),
                recipient=account_id,
                sender='team@reboot.dev',
                domain='reboot.dev',
                subject='Thanks for your time!',
                html=self._html_email,
                text=self._text_email,
            )

        account, _ = await Account.Open(context, account_id)

        await account.Deposit(context, amount=request.initial_deposit)

        # Save the account ID to our _distributed_ map using a UUIDv7
        # to get a "timestamp" based ordering.
        await SortedMap.ref(state.account_ids_map_id).Insert(
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
        from_account = Account.ref(request.from_account_id)
        to_account = Account.ref(request.to_account_id)

        await asyncio.gather(
            from_account.Withdraw(context, amount=request.amount),
            to_account.Deposit(context, amount=request.amount),
        )

        return TransferResponse()

    async def _mailgun_api_key(self) -> Optional[str]:
        try:
            secret_bytes = await self._secrets.get(MAILGUN_API_KEY_SECRET_NAME)
            return secret_bytes.decode()
        except SecretNotFoundException:
            logger.warning(
                "The Mailgun API key secret is not set: please see the README to "
                "enable sending email."
            )
            return None


async def initialize(context: ExternalContext):
    await Bank.idempotently().Create(context, SINGLETON_BANK_ID)


async def main():
    await Application(
        servicers=[AccountServicer, BankServicer] +
        # Include mailgun `Message` servicers.
        reboot.thirdparty.mailgun.servicers() +
        # Include `SortedMap` servicers.
        reboot.std.collections.sorted_map.servicers(),
        initialize=initialize,
    ).run()


if __name__ == '__main__':
    asyncio.run(main())
