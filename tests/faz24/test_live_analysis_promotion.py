import base64
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/faz24'))
import promote_test_live_analysis as promotion


class PromotionTest(unittest.TestCase):
    def run_flow(self, *, apply=True, activation_error=None, rollback_error=None,
                 pin_timeout=False, bad_root=False, repair=False, repair_error=None):
        root=b'public-root-fixture'
        calls=[]

        def remote(script, **kwargs):
            calls.append(script)
            if script == promotion.PREFLIGHT:
                return {'trustRootBase64':base64.b64encode(root).decode(),'repairRequired':repair}
            if script == promotion.PIN.replace('__TARGET__',promotion.TARGET) and pin_timeout:
                raise subprocess.TimeoutExpired('ssh',300)
            if 'source-read-failed' in script:
                return {'source':promotion.TARGET}
            return {'phase':'fixture'}

        policy={'hostStartupGuards':[{'platformAiCommit':s,'startupScriptSha256':promotion.STARTUP_SHA,
                                     'permitRequired':True} for s in (promotion.BASE,promotion.TARGET)],
                'producerCapabilities':[{'transcriptImageDigest':'sha256:'+'a'*64}]}
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            stack.enter_context(patch.object(promotion,'ROOT_SHA','0'*64 if bad_root else hashlib.sha256(root).hexdigest()))
            stack.enter_context(patch.object(promotion.ceremony,'command',return_value='c'*40))
            stack.enter_context(patch.object(promotion.ceremony,'load_strict_json',return_value=(b'policy',policy)))
            stack.enter_context(patch.object(promotion.ceremony,'remote',side_effect=remote))
            repair_call=stack.enter_context(patch.object(promotion.recovery,'corrected_source_recovery',
                side_effect=repair_error,return_value={'status':'processed'}))
            activate=stack.enter_context(patch.object(promotion,'activate',side_effect=
                [activation_error, {'phase':'baseline-permit'}] if activation_error else None,return_value={'phase':'permit'}))
            accept=stack.enter_context(patch.object(promotion,'accept',side_effect=rollback_error,
                                                  return_value={'consumerEnabled':True}))
            report=promotion.perform(apply=apply,output=Path(temp)/'promotion.json')
            report['_repair_calls_for_test']=[(c.args[0],c.kwargs['apply']) for c in repair_call.call_args_list]
            return report,calls,activate,accept

    def test_preflight_is_read_only_and_not_acceptance(self):
        report,calls,activate,accept=self.run_flow(apply=False)
        self.assertEqual(report['status'],'preflight-only')
        self.assertFalse(report['runtimeAccepted'])
        self.assertEqual(calls,[promotion.PREFLIGHT])
        activate.assert_not_called()
        accept.assert_not_called()

    def test_target_requires_fresh_permit_then_full_acceptance(self):
        report,calls,activate,accept=self.run_flow()
        self.assertTrue(report['runtimeAccepted'])
        self.assertFalse(report['phoneAccepted'])
        self.assertEqual(activate.call_args.args[0],promotion.TARGET)
        self.assertEqual(accept.call_args.args[0],promotion.TARGET)
        self.assertIn('source-pinned-not-accepted',calls[2])

    def test_activation_failure_reauthorizes_original_source(self):
        report,calls,activate,accept=self.run_flow(activation_error=RuntimeError('permit-rejected'))
        self.assertEqual(report['status'],'candidate-rejected-baseline-reaccepted')
        self.assertFalse(report['runtimeAccepted'])
        self.assertEqual([c.args[0] for c in activate.call_args_list],[promotion.TARGET,promotion.BASE])
        self.assertEqual(accept.call_args.args[0],promotion.BASE)
        self.assertEqual(calls[-1],promotion.PIN.replace('__TARGET__',promotion.BASE))

    def test_compensation_failure_fences_without_acceptance(self):
        report,calls,_,_=self.run_flow(activation_error=RuntimeError('permit-rejected'),
                                     rollback_error=RuntimeError('runtime-rejected'))
        self.assertEqual(report['status'],'failed')
        self.assertFalse(report['runtimeAccepted'])
        self.assertEqual(calls[-1],promotion.ceremony.FENCE)

    def test_uncertain_pin_does_not_race_second_updater(self):
        report,calls,activate,accept=self.run_flow(pin_timeout=True)
        self.assertEqual(report['failure']['reason'],'host-mutation-completion-unknown')
        self.assertEqual(calls[-1],promotion.ceremony.FENCE)
        self.assertEqual(sum('source-pinned-not-accepted' in c for c in calls),1)
        activate.assert_not_called()
        accept.assert_not_called()

    def test_wrong_root_rejects_before_mutation(self):
        report,calls,_,_=self.run_flow(bad_root=True)
        self.assertEqual(report['status'],'failed')
        self.assertEqual(calls,[promotion.PREFLIGHT])

    def test_unexpected_host_source_rejected(self):
        with self.assertRaisesRegex(ValueError,'unapproved-source'):
            promotion.header('a'*40)

    def test_reviewed_repair_precedes_full_acceptance(self):
        report,calls,activate,accept=self.run_flow(repair=True)
        self.assertEqual(report['_repair_calls_for_test'],[(promotion.BASE,False),(promotion.TARGET,True)])
        self.assertIn(promotion.header(promotion.TARGET)+promotion.START_FOR_REPAIR,calls)
        self.assertEqual(calls[-1],promotion.header(promotion.TARGET)+promotion.FINISH_REPAIR)
        accept.assert_called_once()
        self.assertTrue(report['runtimeAccepted'])

    def test_changed_reviewed_event_rejects_before_source_mutation(self):
        report,calls,activate,accept=self.run_flow(repair=True,repair_error=ValueError('source-changed'))
        self.assertEqual(calls,[promotion.PREFLIGHT])
        self.assertFalse(report['runtimeAccepted'])
        activate.assert_not_called()
        accept.assert_not_called()

    def test_error_does_not_publish_credentials(self):
        error=promotion.safe_error(RuntimeError('token abc / private meeting text'))
        self.assertEqual(error,{'errorClass':'RuntimeError'})

    def test_activation_binds_exact_target_and_fences_before_acceptance(self):
        with tempfile.TemporaryDirectory() as temp:
            work=Path(temp)
            root=work/'root.json'
            root.write_bytes(b'public')
            def issue(root_path,output):
                output.write_bytes(b'public-permit')
            with patch.object(promotion.ceremony,'remote',return_value={}) as remote, \
                 patch.object(promotion.ceremony,'issue_permit',side_effect=issue):
                promotion.activate(promotion.TARGET,root,work,'b'*40,b'policy','sha256:'+'c'*64)
            activation=remote.call_args.args[0]
            self.assertIn(promotion.TARGET,activation)
            self.assertNotIn(promotion.BASE,activation)
            self.assertIn('Assert-TranscriptReadyActivationReceiptFile',activation)
            self.assertIn("Disable-ScheduledTask -TaskName 'platform-ai-meeting-ai'",activation)
            self.assertNotIn('__PERMIT__',activation)

    @unittest.skipUnless(os.name=='nt','Windows PowerShell syntax contract')
    def test_all_embedded_powershell_parses(self):
        with tempfile.TemporaryDirectory() as temp:
            for i,source in enumerate((promotion.PREFLIGHT,promotion.header(promotion.BASE)+promotion.STOP_AND_STAGE,
                                        promotion.PIN.replace('__TARGET__',promotion.TARGET),
                                        promotion.header(promotion.TARGET)+promotion.START_DISABLED,
                                        promotion.header(promotion.TARGET)+promotion.START_FOR_REPAIR,
                                        promotion.header(promotion.TARGET)+promotion.FINISH_REPAIR)):
                path=Path(temp)/f'{i}.ps1'
                path.write_text(source,encoding='utf-8')
                command="$t=$null;$e=$null;[void][Management.Automation.Language.Parser]::ParseFile('"+str(path)+"',[ref]$t,[ref]$e);if($e){$e;exit 1}"
                result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],
                                      capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    @unittest.skipUnless(os.name=='nt','Windows PowerShell child/controller contract')
    def test_pin_executes_separate_controller_and_cleans_it(self):
        with tempfile.TemporaryDirectory(prefix='promotion fixture ') as temp:
            work=Path(temp)
            repo=work/'repo'
            origin=work/'origin.git'
            repo.mkdir()
            def git(*args):
                return subprocess.run(['git',*map(str,args)],check=True,capture_output=True,text=True).stdout.strip()
            git('init','--bare',origin)
            git('-C',repo,'init','-b','main')
            updater=repo/'deploy/gpu-host/update.ps1'
            updater.parent.mkdir(parents=True)
            marker=work/'child-mode.txt'
            updater.write_text("""[CmdletBinding(SupportsShouldProcess=$true)]
param([string]$RepoRoot,[string]$TargetCommit,[switch]$NoRestart)
if ($PSScriptRoot.StartsWith($RepoRoot)) { throw 'controller-is-not-isolated' }
if ($NoRestart) { [IO.File]::WriteAllText('__MARKER__','no-restart') }
exit 0
""".replace('__MARKER__',str(marker).replace("'","''")),encoding='utf-8')
            git('-C',repo,'add','.')
            git('-C',repo,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','fixture')
            git('-C',repo,'remote','add','origin',origin)
            git('-C',repo,'push','origin','main')
            target=git('-C',repo,'rev-parse','HEAD')
            script=work/'pin.ps1'
            script.write_text(promotion.PIN.replace('__TARGET__',target).replace('C:\\platform-ai',str(repo)),encoding='utf-8')
            env=dict(os.environ,TEMP=str(work),TMP=str(work))
            result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-File',str(script)],
                                  capture_output=True,text=True,timeout=40,env=env)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(marker.read_text(),'no-restart')
            self.assertIn('source-pinned-not-accepted',result.stdout)
            self.assertEqual(git('-C',repo,'worktree','list','--porcelain').count('worktree '),1)


if __name__=='__main__':
    unittest.main()
