#!/usr/bin/env python3
"""python3 tests/check_held_item_compat.py (JDK 25; JAVA25_HOME override).

Compiles the full production bridge against real JOML and minimal game stubs.
JOML_JAR / PAL_JAR override local Gradle/Prism discovery. PAL is required for
javap API checks, but never included on the fake-PAL or absent-PAL classpaths.
Limits: matrix-only PoseStack, no normal matrix, game renderer/mixin traversal,
GPU, or actual PAL animation evaluation; javap checks the installed API only.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
JDK = Path(os.environ.get("JAVA25_HOME", "/usr/lib/jvm/java-25-openjdk")) / "bin"
PRISM = [Path.home() / ".local/share/PrismLauncher",
         Path.home() / ".var/app/org.prismlauncher.PrismLauncher/data/PrismLauncher"]


def dependency(variable, candidates):
    paths = [Path(os.environ[variable])] if variable in os.environ else sorted(candidates)
    assert paths and paths[-1].is_file(), f"Set {variable} to an installed jar"
    return paths[-1]


def run(*args):
    return subprocess.run([str(arg) for arg in args], check=True, capture_output=True,
                          text=True).stdout


def main():
    joml = dependency("JOML_JAR", list((Path.home() / ".gradle/caches/modules-2/files-2.1/org.joml/joml").glob("*/*/*.jar")) +
                      [p for root in PRISM for p in (root / "libraries/org/joml/joml").glob("*/*.jar")])
    pal = dependency("PAL_JAR", [p for root in PRISM for p in
                     (root / "instances").glob("*/minecraft/mods/*PlayerAnimation*.jar")])
    accessor = "com.zigythebird.playeranim.accessors.IAvatarAnimationState"
    manager = "com.zigythebird.playeranim.animation.AvatarAnimManager"
    stack = "com.zigythebird.playeranimcore.animation.layered.AnimationStack"
    bone = "com.zigythebird.playeranimcore.bones.PlayerAnimBone"
    api = {name: run(JDK / "javap", "-classpath", pal, name)
           for name in (accessor, manager, stack, bone)}
    assert f"public abstract {manager} playerAnimLib$getAnimManager();" in api[accessor]
    assert f"extends {stack}" in api[manager], "Manager inheritance changed"
    assert "public boolean isActive();" in api[stack]
    assert f"public void get3DTransform({bone});" in api[stack]
    assert f"public {bone}(java.lang.String);" in api[bone]
    for field in ("position", "rotation", "scale"):
        assert re.search(r"public (?:final )?org\.joml\.Vector3f " + field + ";", api[bone])
    print(f"PASS: installed PAL reflection API (including inherited methods): {pal.name}")

    work = ROOT / "tests/.work"
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="held-item-", dir=work) as directory:
        tmp = Path(directory)

        def java(name, text):
            path = tmp / "src" / (name.replace(".", "/") + ".java")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            return path

        stubs = [java("com.mojang.blaze3d.vertex.PoseStack", """
package com.mojang.blaze3d.vertex;
import org.joml.*;
public class PoseStack {
    public final Matrix4f matrix = new Matrix4f();
    public void translate(float x, float y, float z) { matrix.translate(x,y,z); }
    public void mulPose(Quaternionf rotation) { matrix.rotate(rotation); }
    public void scale(float x, float y, float z) { matrix.scale(x,y,z); }
}
"""), java("com.mojang.math.Axis", """
package com.mojang.math;
import org.joml.Quaternionf;
public enum Axis {
    XP, YP, ZP;
    public Quaternionf rotation(float angle) {
        return new Quaternionf().rotationAxis(angle, this == XP ? 1 : 0,
            this == YP ? 1 : 0, this == ZP ? 1 : 0);
    }
}
"""), java("org.figuramc.figura.FiguraMod", """
package org.figuramc.figura;
public class FiguraMod {
    public static final Logger LOGGER = new Logger();
    public static class Logger {
        public int warnings;
        public void warn(String message, Throwable error) {
            if (message.isBlank() || error == null) throw new AssertionError("empty diagnostic");
            warnings++;
        }
    }
}
""")]
        absent = java("AbsentCheck", """
import com.mojang.blaze3d.vertex.PoseStack;
import org.figuramc.figura.compat.PlayerAnimationCompat;
import org.figuramc.figura.FiguraMod;
import org.joml.Matrix4f;
public class AbsentCheck {
    public static void main(String[] args) throws Exception {
        try {
            Class.forName("com.zigythebird.playeranim.accessors.IAvatarAnimationState");
            throw new AssertionError("PAL must actually be absent");
        } catch (ClassNotFoundException expected) {}
        PoseStack pose = new PoseStack();
        pose.matrix.translate(2,3,4).rotateXYZ(.2f,-.3f,.4f).scale(2,3,4);
        Matrix4f before = new Matrix4f(pose.matrix);
        for (int i=0; i<3; i++) for (boolean left : new boolean[]{false,true}) {
            PlayerAnimationCompat.applyItemTransform(null, left, pose);
            PlayerAnimationCompat.applyItemTransform(new Object(), left, pose);
        }
        if (!before.equals(pose.matrix) || FiguraMod.LOGGER.warnings != 0)
            throw new AssertionError("absent PAL changed matrix/logged");
    }
}
""")
        fake = [java(bone, """
package com.zigythebird.playeranimcore.bones;
import org.joml.Vector3f;
public class PlayerAnimBone {
    public final String name;
    public final Vector3f position = new Vector3f(), rotation = new Vector3f(), scale = new Vector3f(1);
    public PlayerAnimBone(String name) { this.name = name; }
}
"""), java(stack, """
package com.zigythebird.playeranimcore.animation.layered;
import com.zigythebird.playeranimcore.bones.PlayerAnimBone;
import org.joml.Vector3f;
import java.util.*;
public class AnimationStack {
    public final Vector3f[] pos = {new Vector3f(), new Vector3f()};
    public final Vector3f[] rot = {new Vector3f(), new Vector3f()};
    public final Vector3f[] size = {new Vector3f(1), new Vector3f(1)};
    public boolean active = true;
    public String failure = "";
    public int activeCalls, transformCalls;
    private final Set<PlayerAnimBone> seen = Collections.newSetFromMap(new IdentityHashMap<>());
    public boolean isActive() {
        activeCalls++;
        if (failure.equals("active")) throw new IllegalStateException("active failure");
        return active;
    }
    public void get3DTransform(PlayerAnimBone bone) {
        transformCalls++;
        if (!seen.add(bone) || !bone.position.equals(new Vector3f()) ||
            !bone.rotation.equals(new Vector3f()) || !bone.scale.equals(new Vector3f(1)))
            throw new AssertionError("bone reused or not identity");
        int hand = switch (bone.name) {
            case "right_item" -> 0;
            case "left_item" -> 1;
            default -> throw new AssertionError("wrong bone: " + bone.name);
        };
        bone.position.set(pos[hand]); bone.rotation.set(rot[hand]); bone.scale.set(size[hand]);
        // Fail after touching the scratch bone: no partial pose may escape.
        if (failure.equals("transform")) throw new IllegalStateException("transform failure");
        if (failure.equals("linkage")) throw new NoClassDefFoundError("injected missing PAL dependency");
    }
}
"""), java(manager, """
package com.zigythebird.playeranim.animation;
public class AvatarAnimManager extends com.zigythebird.playeranimcore.animation.layered.AnimationStack {}
"""), java(accessor, """
package com.zigythebird.playeranim.accessors;
import com.zigythebird.playeranim.animation.AvatarAnimManager;
public interface IAvatarAnimationState {
    boolean playerAnimLib$isFirstPersonPass();
    void playerAnimLib$setFirstPersonPass(boolean value);
    void playerAnimLib$setAnimManager(AvatarAnimManager manager);
    AvatarAnimManager playerAnimLib$getAnimManager();
}
""")]
        check = java("HeldItemCheck", """
import com.mojang.blaze3d.vertex.PoseStack;
import com.zigythebird.playeranim.accessors.IAvatarAnimationState;
import com.zigythebird.playeranim.animation.AvatarAnimManager;
import org.figuramc.figura.compat.PlayerAnimationCompat;
import org.figuramc.figura.FiguraMod;
import org.joml.*;
public class HeldItemCheck {
    public static class State implements IAvatarAnimationState {
        public AvatarAnimManager manager = new AvatarAnimManager();
        public int calls;
        public boolean fail;
        public AvatarAnimManager playerAnimLib$getAnimManager() {
            calls++;
            if (fail) throw new IllegalStateException("manager failure");
            return manager;
        }
        public boolean playerAnimLib$isFirstPersonPass() { return false; }
        public void playerAnimLib$setFirstPersonPass(boolean value) {}
        public void playerAnimLib$setAnimManager(AvatarAnimManager value) { manager = value; }
    }
    static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    static PoseStack pose() {
        PoseStack pose = new PoseStack();
        pose.matrix.translate(2.3f,-1.7f,4.1f).rotateXYZ(.31f,-.47f,.83f).scale(1.2f,.7f,-1.4f);
        return pose;
    }
    // Independent double-precision reference: retain the hand-space conjugation,
    // rather than copying production's simplified translation or quaternion path.
    static Matrix4d expected(Matrix4d base, AvatarAnimManager m, int hand) {
        Vector3f p=m.pos[hand], r=m.rot[hand], s=m.size[hand];
        Matrix4d vanilla = new Matrix4d().rotateX(-java.lang.Math.PI/2).rotateY(java.lang.Math.PI);
        Matrix4d result = new Matrix4d(base).mul(new Matrix4d(vanilla).invert())
            .translate(p.x/16.0,-p.y/16.0,p.z/16.0).mul(vanilla);
        if (r.z != 0) result.rotateZ(-r.y);
        if (r.y != 0) result.rotateY(-r.z);
        if (r.x != 0) result.rotateX(-r.x);
        return result.scale(s.x,s.y,s.z);
    }
    static void equal(Matrix4d expected, PoseStack actual, String label) {
        double[] want = expected.get(new double[16]);
        float[] got = actual.matrix.get(new float[16]);
        for (int i=0; i<16; i++)
            require(Double.isFinite(got[i]) && java.lang.Math.abs(want[i]-got[i]) < 8e-6,
                label + " entry " + i + ": expected " + want[i] + ", got " + got[i]);
    }
    static void unchanged(Object state, boolean left) {
        PoseStack p = pose(); Matrix4f before = new Matrix4f(p.matrix);
        PlayerAnimationCompat.applyItemTransform(state,left,p);
        require(before.equals(p.matrix), "bypass/error partially changed pose");
    }
    public static void main(String[] args) {
        State state = new State(); AvatarAnimManager m = state.manager;
        for (boolean left : new boolean[]{false,true}) {
            unchanged(null,left); unchanged(new Object(),left);
            state.manager=null; unchanged(state,left); state.manager=m;
            m.active=false; unchanged(state,left); m.active=true;
        }
        require(m.transformCalls == 0 && FiguraMod.LOGGER.warnings == 0, "bypass touched PAL/logged");
        if (!args[0].equals("matrix")) {
            m.pos[0].set(9,8,7); m.pos[1].set(-9,-8,-7);
            m.failure=args[0]; state.fail=args[0].equals("manager");
            unchanged(state,Boolean.parseBoolean(args[1]));
            require(FiguraMod.LOGGER.warnings == 1, "failure was not logged once");
            int calls=state.calls, active=m.activeCalls, transforms=m.transformCalls;
            state.fail=false; m.failure="";
            for (int i=0; i<3; i++) for (boolean left : new boolean[]{false,true}) unchanged(state,left);
            require(state.calls==calls && m.activeCalls==active && m.transformCalls==transforms,
                "bridge was not disabled after failure");
            require(FiguraMod.LOGGER.warnings == 1, "repeated failure logging");
            return;
        }
        float[][] cases = {
            // position XYZ, rotation XYZ (radians), scale XYZ
            {0,0,0, 0,0,0, 1,1,1},
            {11,0,0, 0,0,0, 1,1,1}, {0,-7,0, 0,0,0, 1,1,1}, {0,0,5, 0,0,0, 1,1,1},
            {0,0,0, .37f,0,0, 1,1,1}, {0,0,0, 0,-.61f,0, 1,1,1},
            {0,0,0, 0,0,.82f, 1,1,1}, {0,0,0, 0,-.61f,.82f, 1,1,1},
            {0,0,0, .37f,-.61f,.82f, 1,1,1},
            {0,0,0, 0,0,0, 1.3f,.6f,-.8f}, {0,0,0, 0,0,0, 0,1,1},
            {11,-7,5, .37f,-.61f,.82f, 1.3f,.6f,-.8f}
        };
        int before=m.transformCalls;
        for (float[] c : cases) {
            for (int hand=0; hand<2; hand++) {
                float sign=hand==0 ? 1 : -1;
                m.pos[hand].set(c[0]*sign,c[1]*sign,c[2]*sign);
                m.rot[hand].set(c[3]*sign,c[4]*sign,c[5]*sign);
                m.size[hand].set(c[6],c[7],c[8]);
            }
            PoseStack accumulated=pose(); Matrix4d reference=new Matrix4d(accumulated.matrix);
            for (int repeat=0; repeat<3; repeat++) for (int hand=0; hand<2; hand++) {
                PoseStack fresh=pose();
                Matrix4d want=expected(new Matrix4d(fresh.matrix),m,hand);
                PlayerAnimationCompat.applyItemTransform(state,hand==1,fresh);
                equal(want,fresh,"fresh hand " + hand);
                reference=expected(reference,m,hand);
                PlayerAnimationCompat.applyItemTransform(state,hand==1,accumulated);
                equal(reference,accumulated,"accumulated hand " + hand);
            }
        }
        require(m.transformCalls-before == cases.length*12, "missing/extra PAL transforms");
        for (int hand=0; hand<2; hand++) {
            m.pos[hand].zero(); m.rot[hand].zero(); m.size[hand].set(1);
            unchanged(state,hand==1); // prior animated scratch data must not leak
        }
        require(FiguraMod.LOGGER.warnings==0, "healthy PAL unexpectedly disabled");
    }
}
""")
        classes, pal_classes = tmp / "classes", tmp / "fake-pal"
        source = ROOT / "common/src/main/java/org/figuramc/figura/compat/PlayerAnimationCompat.java"
        run(JDK / "javac", "--release", "25", "-cp", joml, "-d", classes, *stubs, source, absent)
        run(JDK / "javac", "--release", "25", "-cp", os.pathsep.join(map(str, (classes, joml))),
            "-d", pal_classes, *fake, check)
        base_cp = os.pathsep.join(map(str, (classes, joml)))
        run(JDK / "java", "-cp", base_cp, "AbsentCheck")
        present_cp = os.pathsep.join((base_cp, str(pal_classes)))
        run(JDK / "java", "-cp", present_cp, "HeldItemCheck", "matrix")
        for failure in ("manager", "active", "transform", "linkage"):
            for left in ("false", "true"):
                run(JDK / "java", "-cp", present_cp, "HeldItemCheck", failure, left)
    print("PASS: full production bridge; absent/null/non-PAL/inactive; both hands, each axis, "
          "combined/identity/scale, repeated and accumulated transforms; no scratch leakage; "
          "manager/getter/transform/linkage failures log once and disable without partial matrices")
    print("Limits: matrix-only game stubs; installed PAL API checked, not animation evaluation or rendering.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        print(error.stdout or "", end="")
        print(error.stderr or "", end="")
        raise
