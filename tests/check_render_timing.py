#!/usr/bin/env python3
"""Run extracted hook dispatch with JDK25; no game/mixin weaving is simulated."""
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
JDK = Path(os.environ.get('JAVA25_HOME', '/usr/lib/jvm/java-25-openjdk')) / 'bin'
source = (ROOT / 'common/src/main/java/org/figuramc/figura/mixin/render/renderers/LivingEntityRendererMixin.java').read_text()
methods = []
for name, target in [('submitFiguraModel', 'EntityModel;setupAnim'),
                     ('submitFollowingFiguraModel', 'List;iterator')]:
    annotation, method = re.search(r'(@Inject[^\n]+)\n    (private void ' + name + r'\([^\n]+\) \{.*?\n    \})', source, re.S).groups()
    # Restrict to the annotation directly preceding this method.
    annotation = annotation.splitlines()[-1]
    assert target in annotation
    if name == 'submitFiguraModel':
        assert 'shift = At.Shift.AFTER' in annotation
    methods.append(method)
java = '''
public class TimingCheck {
    static class S {} static class PoseStack {} static class SubmitNodeCollector {}
    static class CameraRenderState {} static class CallbackInfo {}
    static class Avatar { boolean follow; boolean followsVanillaPose() { return follow; } }
    Avatar currentAvatar;
    int calls;
    boolean firstPerson, packPose;
    boolean capturedPack;
    void figura$submitModel(S s, PoseStack p, SubmitNodeCollector n, CameraRenderState c, CallbackInfo ci) {
        calls++; capturedPack = packPose;
        if (firstPerson) currentAvatar = null;
    }
''' + '\n'.join(methods) + '''
    public static void main(String[] args) {
        for (boolean follow : new boolean[]{false,true})
        for (boolean firstPerson : new boolean[]{false,true}) {
            TimingCheck t = new TimingCheck();
            t.currentAvatar = new Avatar(); t.currentAvatar.follow = follow;
            t.firstPerson = firstPerson;
            t.submitFiguraModel(null,null,null,null,null);
            if (t.calls != (follow ? 0 : 1)) throw new AssertionError("upstream dispatch");
            t.packPose = true; // model later modified by resource-pack hook
            t.submitFollowingFiguraModel(null,null,null,null,null);
            if (t.calls != 1 || t.capturedPack != follow) throw new AssertionError("duplicate/wrong timing");
        }
        TimingCheck absent = new TimingCheck();
        absent.submitFiguraModel(null,null,null,null,null);
        absent.submitFollowingFiguraModel(null,null,null,null,null);
        if (absent.calls != 0) throw new AssertionError("no avatar");
    }
}
'''
work = ROOT / 'tests/.work'
work.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(dir=work, prefix='timing-') as directory:
    path = Path(directory) / 'TimingCheck.java'
    path.write_text(java)
    subprocess.run([str(JDK/'javac'), '-d', directory, str(path)], check=True)
    subprocess.run([str(JDK/'java'), '-cp', directory, 'TimingCheck'], check=True)
print('PASS: OFF uses upstream hook; ON uses late hook; one submission, first-person and absent-avatar cases')
