"""
This test reproduce that current swap still exist in the new marketplace.

All current contracts code except the marketplace are taken from the mainnet:
curation:    https://better-call.dev/mainnet/KT1TybhR7XraG75JFYKSrh7KnxukMBT5dor6/code
fa2_hdao:    https://better-call.dev/mainnet/KT1AFA2mwNUMNd4SsujE1YYp29vd8BZejyKW/code
fa2_objkts:  https://better-call.dev/mainnet/KT1RJ6PbjHpwc3M5rw5s2Nbmefwbuwbdxton/code
marketplace: https://github.com/hicetnunc2000/smart-contracts/blob/master/michelson/marketplace.tz
objkt_swap:  https://better-call.dev/mainnet/KT1Hkg5qeNhfwpKW4fXvq7HGZB9z2EnmCCA9/code

"""

from pytezos.sandbox.node import SandboxedNodeTestCase
from pytezos.sandbox.parameters import sandbox_addresses, sandbox_commitment
from pytezos import ContractInterface, pytezos
from pytezos.rpc.errors import MichelsonError
from pytezos.contract.result import ContractCallResult
import unittest
from os.path import dirname, join
import json


CONTRACTS_DIR = 'contracts'


def pkh(key):
    return key.key.public_key_hash()


def read_contract(name):
    """ Loads contract from CONTRACTS_DIR with name {name}.tz """

    filename = join(dirname(__file__), CONTRACTS_DIR, f'{name}.tz')
    return ContractInterface.from_file(filename)


def read_storage(name):
    """ Loads storage from CONTRACTS_DIR with name {name}.json """

    filename = join(dirname(__file__), CONTRACTS_DIR, f'{name}.json')
    with open(filename, 'r') as f:
        return json.loads(f.read())


class ContractInteractionsTestCase(SandboxedNodeTestCase):


    def _deploy_contract(self, client, contract, storage):
        """ Deploys contract with given storage """

        # TODO: try to replace key with client.key:
        opg = contract.using(shell=self.get_node_url(), key=client.key)
        opg = opg.originate(initial_storage=storage)

        return opg.fill().sign().inject()


    def _find_call_result_by_hash(self, client, opg_hash):

        # Get injected operation and convert to ContractCallResult
        opg = client.shell.blocks['head':].find_operation(opg_hash)
        return ContractCallResult.from_operation_group(opg)[0]


    def _load_contract(self, client, contract_address):

        # Load originated contract from blockchain
        contract = client.contract(contract_address)
        contract = contract.using(
            shell=self.get_node_url(),
            key='bootstrap1')
        return contract


    def _find_contract_by_hash(self, client, opg_hash):
        """ Returns contract that was originated with opg_hash """

        op = client.shell.blocks['head':].find_operation(opg_hash)
        op_result = op['contents'][0]['metadata']['operation_result']
        address = op_result['originated_contracts'][0]

        return self._load_contract(client, address)


    def _find_contract_internal_by_hash(self, client, opg_hash):
        """ Returns collab that was originated with opg_hash """

        op = client.shell.blocks['head':].find_operation(opg_hash)
        int_op = op['contents'][0]['metadata']['internal_operation_results']
        address = int_op[0]['result']['originated_contracts'][0]

        return self._load_contract(client, address)


    def _activate_accs(self):
        self.p1 = self.client.using(key='bootstrap1')
        self.p1.reveal()

        self.p2 = self.client.using(key='bootstrap2')
        self.p2.reveal()

        self.hic_admin = self.client.using(key='bootstrap4')
        self.hic_admin.reveal()

        self.buyer = self.client.using(key='bootstrap5')
        self.buyer.reveal()


    def _deploy_hic_contracts(self, client):
        # Deploying OBJKTs:
        storage = read_storage('fa2_objkts')
        storage.update({'administrator': pkh(client)})
        opg = self._deploy_contract(
            client=client,
            contract=read_contract('fa2_objkts'),
            storage=storage)

        self.bake_block()
        self.objkts = self._find_contract_by_hash(client, opg['hash'])

        # Deploying hDAO:
        storage = read_storage('fa2_hdao')
        storage.update({'administrator': pkh(client)})
        opg = self._deploy_contract(
            client=client,
            contract=read_contract('fa2_hdao'),
            storage=storage)

        self.bake_block()
        self.hdao = self._find_contract_by_hash(client, opg['hash'])

        # Deploying curate:
        storage = read_storage('curation')
        storage.update({
            'manager': pkh(client)
        })

        opg = self._deploy_contract(
            client=client,
            contract=read_contract('curation'),
            storage=storage)

        self.bake_block()
        self.curate = self._find_contract_by_hash(client, opg['hash'])

        # Deploying objkt_swap:
        storage = read_storage('objkt_swap')
        storage.update({
            'curate': self.curate.address,
            'hdao': self.hdao.address,
            'objkt': self.objkts.address,
            'manager': pkh(client) 
        })
        opg = self._deploy_contract(
            client=client,
            contract=read_contract('objkt_swap'),
            storage=storage)

        self.bake_block()
        self.minter = self._find_contract_by_hash(client, opg['hash'])

        # configure curate:
        configuration = {
            'fa2': self.hdao.address,
            'protocol': self.minter.address
        }
        self.curate.configure(configuration).inject()
        self.bake_block()

        # what does this genesis?:
        self.minter.genesis().inject()
        self.bake_block()

        # configure objkts and hdao:
        self.objkts.set_administrator(self.minter.address).inject()
        self.hdao.set_administrator(self.minter.address).inject()
        self.bake_block()

        # Deploying Marketplace:
        storage = read_storage('marketplace')
        storage.update({
            'objkt': self.objkts.address,
            'manager': pkh(client)
        })
        opg = self._deploy_contract(
            client=client,
            contract=read_contract('marketplace'),
            storage=storage)

        self.bake_block()
        self.marketplace = self._find_contract_by_hash(client, opg['hash'])


    def _add_operator(self, contract, owner_client, operator, token_id):
        fa2_contract = owner_client.contract(contract.address)
        update_operatiors_params = [{
            'add_operator': {
                'owner': pkh(owner_client),
                'operator': operator,
                'token_id': token_id}
        }]

        return fa2_contract.update_operators(update_operatiors_params).inject()


    def setUp(self):
        self._activate_accs()
        self._deploy_hic_contracts(self.hic_admin)


    def test_marketplace_communication(self):

        # mint:
        mint_params = {
            'address': pkh(self.p1),
            'amount': 100,
            'metadata': '697066733a2f2f516d5952724264554578587269473470526679746e666d596b664a4564417157793632683746327771346b517775',
            'royalties': 100
        }

        minter = self.p1.contract(self.minter.address)
        opg = minter.mint_OBJKT(mint_params).inject()
        self.bake_block()
        result = self._find_call_result_by_hash(self.p1, opg['hash'])

        # update operators:
        self._add_operator(self.objkts, self.p1, self.marketplace.address, 0)
        self.bake_block()

        # swap:
        swap_params = {
            'creator': pkh(self.p1),
            'objkt_amount': 100,
            'objkt_id': 0,
            'royalties': 100,
            'xtz_per_objkt': 1_000_000,
        }

        marketplace = self.p1.contract(self.marketplace.address)
        swap_id = marketplace.storage['counter']()
        opg = marketplace.swap(swap_params).inject()
        self.bake_block()
        result = self._find_call_result_by_hash(self.p1, opg['hash'])

        # collect:
        opg = self.buyer.contract(self.marketplace.address).collect(
            swap_id).with_amount(1_000_000).inject()

        self.bake_block()
        result = self._find_call_result_by_hash(self.p1, opg['hash'])
        assert self.objkts.storage['ledger'][(pkh(self.buyer), 0)]() == 1

        # reswap this one objkt with low price:
        self._add_operator(self.objkts, self.buyer, self.marketplace.address, 0)
        self.bake_block()

        marketplace = self.buyer.contract(self.marketplace.address)
        swap_id = marketplace.storage['counter']()

        swap_params.update({
            'objkt_amount': 1,
            'xtz_per_objkt': 100
        })
        opg = marketplace.swap(swap_params).inject()
        self.bake_block()
        result = self._find_call_result_by_hash(self.p1, opg['hash'])

        # rebuing second swap:
        opg = self.p2.contract(self.marketplace.address).collect(
            swap_id).with_amount(1*100).inject()
        self.bake_block()
        result = self._find_call_result_by_hash(self.p1, opg['hash'])

        # and p2 should not receive this 1 objkt:
        assert self.objkts.storage['ledger'][(pkh(self.p2), 0)]() == 1
        assert self.objkts.storage['ledger'][(self.marketplace.address, 0)]() == 99

        # Trying to use this second swap second time:
        with self.assertRaises(MichelsonError) as cm:
            opg = self.p2.contract(self.marketplace.address).collect(
                swap_id).with_amount(1*100).inject()
            self.bake_block()
            result = self._find_call_result_by_hash(self.p1, opg['hash'])

        # Trying to collect swap that does not exist:
        with self.assertRaises(MichelsonError) as cm:
            opg = self.p2.contract(self.marketplace.address).collect(
                3).with_amount(1*100).inject()
            self.bake_block()

        # 0-tez swap
        self._add_operator(self.objkts, self.p2, self.marketplace.address, 0)
        self.bake_block()

        marketplace = self.p2.contract(self.marketplace.address)
        swap_id = marketplace.storage['counter']()

        swap_params.update({
            'objkt_amount': 1,
            'xtz_per_objkt': 0
        })
        opg = marketplace.swap(swap_params).inject()
        self.bake_block()

        opg = self.buyer.contract(self.marketplace.address).collect(
            swap_id).with_amount(0).inject()
        self.bake_block()

        assert self.objkts.storage['ledger'][(pkh(self.buyer), 0)]() == 1
        assert self.objkts.storage['ledger'][(self.marketplace.address, 0)]() == 99

        # Trying to swap more objects that have:
        with self.assertRaises(MichelsonError) as cm:
            marketplace = self.buyer.contract(self.marketplace.address)
            swap_id = marketplace.storage['counter']()

            swap_params.update({
                'objkt_amount': 2,
                'xtz_per_objkt': 0
            })
            opg = marketplace.swap(swap_params).inject()
            self.bake_block()

        self.assertTrue('FA2_INSUFFICIENT_BALANCE' in str(cm.exception))


        # Trying to sell objkt for price that leads to 0-fees trans:
        # this is raising contract.empty_transaction but it should not
        marketplace = self.buyer.contract(self.marketplace.address)
        swap_id = marketplace.storage['counter']()

        swap_params.update({
            'objkt_amount': 1,
            'xtz_per_objkt': 10
        })
        opg = marketplace.swap(swap_params).inject()
        self.bake_block()

        opg = self.p2.contract(self.marketplace.address).collect(
            swap_id).with_amount(10).inject()
        self.bake_block()

