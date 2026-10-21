"""Connect retry across the real loopback proxy; fake sockets never reach a model."""
import asyncio
import io
import json
import os
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from policy_sim.proxy import BudgetLedger, BudgetProxy, LOCAL_KEY
from policy_sim.profiles import make_profile, profile_digest, settings_for_purpose

class FakeSocket:
    def __init__(self, sends, read_error=False):
        self.sends=sends; self.read_error=read_error
    def settimeout(self, value): pass
    def close(self): pass
    def sendall(self, data): self.sends.append(bytes(data))
    def makefile(self, *args):
        if self.read_error: raise TimeoutError('secret-not-to-log')
        body=json.dumps({'id':'offline', 'object':'chat.completion', 'created':0,
            'model':'deepseek-flash','choices':[{'index':0,'finish_reason':'stop',
            'message':{'role':'assistant','content':'ok'}}],
            'usage':{'prompt_tokens':2,'completion_tokens':3,'total_tokens':5}}).encode()
        return io.BytesIO(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: '+str(len(body)).encode()+b'\r\nConnection: close\r\n\r\n'+body)

class TransportTests(unittest.TestCase):
    def exercise(self, failures=2, read_error=False, certificate_error=False):
        import uuid
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        profile=make_profile(provider='deepseek_official')
        ledger=BudgetLedger(Path(tmp.name)/'ledger.json',model='deepseek-flash',max_output_tokens=16384)
        connects=[];sends=[]
        def connect(conn):
            connects.append(conn.host)
            if certificate_error: raise ssl.SSLCertVerificationError('secret-not-to-log')
            if len(connects)<=failures: raise TimeoutError('secret-not-to-log')
            conn.sock=FakeSocket(sends,read_error)
        with patch('http.client.HTTPSConnection.connect',connect),patch('policy_sim.proxy.time.sleep'):
            with BudgetProxy('fake-offline',ledger,native_idempotency=True,native_profiles=[profile],
                    provider_route=profile['provider_route'],upstream_timeout_seconds=600) as proxy:
                rid=str(uuid.uuid4())
                payload={**settings_for_purpose(profile),'messages':[{'role':'user','content':'offline'}]}
                request=Request(proxy.base_url+'/chat/completions',data=json.dumps(payload).encode(),headers={
                    'Authorization':'Bearer '+LOCAL_KEY,'Content-Type':'application/json',
                    'X-Client-Request-Id':rid,'X-Native-Purpose':'agent_decision','X-Native-Profile-Sha256':profile_digest(profile)})
                results=[]
                for _ in range(2):
                    try:
                        with urlopen(request) as response:results.append((response.status,response.read()))
                    except HTTPError as error:results.append((error.code,error.read()))
                self.assertEqual(results[0],results[1], 'Same UUID delivery must not repeat upstream work')
                fatal=proxy.fatal_event.is_set()
        self.assertEqual(len(ledger.records),1)
        self.assertNotIn('secret-not-to-log',json.dumps(ledger.records))
        return results[0][0],connects,sends,ledger.records[0],fatal

    def test_connect_failure_then_success_sends_once_and_counts_once(self):
        status,connects,sends,row,fatal=self.exercise()
        self.assertEqual(status,200)
        self.assertEqual(connects,['api.deepseek.com']*3)
        self.assertEqual(sum(b'offline' in s for s in sends),2) # header fake-offline and body
        self.assertEqual(row['prompt_tokens']+row['completion_tokens'],5)
        self.assertFalse(fatal)
        failed=[e for e in row['transport_events'] if e.get('status')=='failed']
        self.assertEqual(len(failed),2)
        self.assertTrue(all(e['request_sent'] is False and e['retry'] for e in failed))

    def test_post_send_timeout_not_replayed_and_remains_unknown(self):
        status,connects,sends,row,fatal=self.exercise(failures=0,read_error=True)
        self.assertEqual(status,502);self.assertEqual(len(connects),1)
        self.assertTrue(sends);self.assertTrue(fatal)
        self.assertNotIn('prompt_tokens',row)
        self.assertEqual(row['transport_events'][-1]['cause_type'],'TimeoutError')
        self.assertTrue(any(e['phase']=='http_send' for e in row['transport_events']))

    def test_certificate_failure_is_not_retried(self):
        status,connects,sends,row,fatal=self.exercise(certificate_error=True)
        self.assertEqual(status,502);self.assertEqual(len(connects),1)
        self.assertFalse(sends);self.assertTrue(fatal)

    def test_connection_exhaustion_has_no_http_send(self):
        status,connects,sends,row,fatal=self.exercise(failures=99)
        self.assertEqual(status,502);self.assertEqual(len(connects),3)
        self.assertFalse(sends);self.assertTrue(fatal)
        self.assertEqual(len([e for e in row['transport_events'] if e.get('status')=='failed' and e['phase']=='connect_or_tls']),3)
