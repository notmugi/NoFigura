#!/usr/bin/env python3
"""python3 tests/check_emf_compat.py (JDK 25; JAVA25_HOME override).

Compile both complete production bridges, not extracted/copied methods.
Python stdlib/JDK and installed JOML (JOML_JAR override) are required;
temporary files stay under tests/.work.
EMF_JAR optionally selects an installed jar for a javap signature check; otherwise
PrismLauncher mods matching the project's Minecraft version are discovered.
PAL_JAR optionally selects PAL for the bundled EMF hook bytecode diagnostic.
Real EMF/PAL never enter the runtime classpaths.
Limits: game/avatar/config/panic behavior is stubbed; no mixins, EMF model
selection, resource packs, rendering, or live game lifecycle is exercised.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

sys.dont_write_bytecode = True
from check_held_item_compat import PRISM, fake_pal, game_stubs, joml_dependency

ROOT = Path(__file__).resolve().parents[1]
JDK = Path(os.environ.get("JAVA25_HOME", "/usr/lib/jvm/java-25-openjdk")) / "bin"
API = "traben.entity_model_features.EMFAnimationApi"


def run(*args):
    return subprocess.run([str(arg) for arg in args], check=True,
                          capture_output=True, text=True).stdout


def installed_api_check():
    if "EMF_JAR" in os.environ:
        jars = [Path(os.environ["EMF_JAR"])]
        assert jars[0].is_file(), "EMF_JAR must name an installed jar"
    else:
        version = next(line.split("=", 1)[1].strip()
                       for line in (ROOT / "gradle.properties").read_text().splitlines()
                       if line.split("=", 1)[0].strip() == "minecraft_version")
        jars = sorted({p for root in PRISM for p in
                       (root / "instances").glob("*/minecraft/mods/entity_model_features*.jar")
                       if f"-{version}-" in p.name or f"_{version}-" in p.name})
    if not jars:
        print("SKIP: installed EMF javap check (set EMF_JAR to enable)")
    pal_jars = ([Path(os.environ["PAL_JAR"])] if "PAL_JAR" in os.environ else
                sorted({p for root in PRISM for p in
                        (root / "instances").glob("*/minecraft/mods/*PlayerAnimation*.jar")}))
    stale = "traben/entity_model_features/models/animation/EMFAnimationEntityContext"
    for pal in pal_jars:
        mixin = "com.zigythebird.playeranim.mixin.FixEmfPauseMixin"
        with zipfile.ZipFile(pal) as archive:
            if mixin.replace(".", "/") + ".class" not in archive.namelist():
                print(f"SKIP: no bundled FixEmfPauseMixin: {pal.name}")
                continue
        bytecode = run(JDK / "javap", "-classpath", pal, "-c", "-p", "-verbose", mixin)
        if stale not in bytecode:
            print(f"INFO: PAL no longer references stale EMF context: {pal.name}")
            continue
        for jar in jars:
            with zipfile.ZipFile(jar) as archive:
                absent = stale + ".class" not in archive.namelist()
            print(f"PASS: installed PAL stale EMF context reference confirmed; "
                  f"class {'absent' if absent else 'present'} in {jar.name}")
    for jar in jars:
        signature = run(JDK / "javap", "-classpath", jar, "-s", API)
        expected = ("public static boolean registerVanillaModelCondition("
                    "java.util.function.Function<traben.entity_model_features.utils.EMFEntity, "
                    "java.lang.Boolean>) throws java.lang.Exception;")
        assert expected.replace("registerVanillaModelCondition", "registerPauseCondition") in signature
        assert expected in signature, f"EMF registration signature changed: {jar}"
        method = signature.split(expected, 1)[1].splitlines()[1].strip()
        assert method == "descriptor: (Ljava/util/function/Function;)Z", method
        print(f"PASS: installed EMF registration API: {jar}")


def main():
    version = run(JDK / "javac", "-version").strip()
    assert version.startswith("javac 25"), f"JDK 25 required, got {version}"
    installed_api_check()
    joml = joml_dependency()
    work = ROOT / "tests/.work"
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="emf-", dir=work) as directory:
        tmp = Path(directory)

        def java(name, text, group="base"):
            path = tmp / group / "src" / (name.replace(".", "/") + ".java")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            return path

        stubs = game_stubs(java) + [java("net.minecraft.client.Minecraft", """
package net.minecraft.client;
import java.util.UUID;
public class Minecraft {
    private static final Minecraft INSTANCE = new Minecraft();
    public Object level;
    public Player player;
    public static Minecraft getInstance() { return INSTANCE; }
    public static class Player extends net.minecraft.world.entity.Avatar {
        private final UUID uuid;
        public Player(UUID uuid) { this.uuid = uuid; }
        public UUID getUUID() { return uuid; }
    }
}
"""), java("org.figuramc.figura.avatar.Avatar", """
package org.figuramc.figura.avatar;
public class Avatar {
    public boolean isHost = true, loaded = true, followVanillaPose;
    public Object renderer = new Object();
    public boolean followsVanillaPose() { return isHost && followVanillaPose; }
}
"""), java("org.figuramc.figura.avatar.AvatarManager", """
package org.figuramc.figura.avatar;
import java.util.*;
import net.minecraft.client.Minecraft;
public class AvatarManager {
    public static final Map<UUID, Avatar> avatars = new HashMap<>();
    public static boolean panic;
    public static int lookups;
    // Deliberately no fetching/creating API: production must compile with only this lookup.
    // Mirrors the real getLoadedAvatar panic/world guards; not testing that implementation.
    public static Avatar getLoadedAvatar(UUID owner) {
        lookups++;
        if (panic || Minecraft.getInstance().level == null) return null;
        return avatars.get(owner);
    }
}
""")]
        init_check = java("InitCheck", """
import org.figuramc.figura.FiguraMod;
import org.figuramc.figura.compat.EmfCompat;
import org.figuramc.figura.avatar.AvatarManager;
public class InitCheck {
    public static void main(String[] args) throws Exception {
        boolean absent = args[0].equals("absent");
        if (absent) {
            try {
                Class.forName("traben.entity_model_features.EMFAnimationApi");
                throw new AssertionError("EMF must actually be absent");
            } catch (ClassNotFoundException expected) {}
        }
        for (int i = 0; i < 4; i++) {
            EmfCompat.init();
            if (FiguraMod.LOGGER.warnings != (absent ? 0 : 1))
                throw new AssertionError("wrong warning count on init " + i);
        }
        if (!absent && !Class.forName(args[0]).isInstance(FiguraMod.LOGGER.lastError))
            throw new AssertionError("wrong registration failure", FiguraMod.LOGGER.lastError);
        if (AvatarManager.lookups != 0) throw new AssertionError("init accessed avatars");
    }
}
""")
        classes = tmp / "classes"
        source = ROOT / "common/src/main/java/org/figuramc/figura/compat/EmfCompat.java"
        pal_source = source.with_name("PlayerAnimationCompat.java")
        run(JDK / "javac", "--release", "25", "-cp", joml, "-d", classes,
            *stubs, source, pal_source, init_check)
        base_cp = os.pathsep.join(map(str, (classes, joml)))
        run(JDK / "java", "-cp", base_cp, "InitCheck", "absent")
        print("PASS: both production bridges compile without fetching APIs; EMF absent in separate JVM")

        fake = java(API, """
package traben.entity_model_features;
import java.util.function.Function;
public class EMFAnimationApi {
    public static int registrations, pauses;
    public static Function<Object, Boolean> pauseCondition;
    public static boolean registerPauseCondition(Function<Object, Boolean> callback) {
        pauses++; pauseCondition = callback; return true;
    }
    public static Function<Object, Boolean> condition;
    // Same erased signature as real EMF; Object avoids requiring EMF mixins in game stubs.
    public static boolean registerVanillaModelCondition(Function<Object, Boolean> callback) throws Exception {
        registrations++;
        condition = callback;
        return true;
    }
}
""", "healthy")
        check = java("CallbackCheck", """
import java.util.UUID;
import java.util.function.Function;
import net.minecraft.client.Minecraft;
import net.minecraft.client.Minecraft.Player;
import org.figuramc.figura.FiguraMod;
import org.figuramc.figura.avatar.*;
import org.figuramc.figura.compat.EmfCompat;
import traben.entity_model_features.EMFAnimationApi;
public class CallbackCheck {
    static Function<Object, Boolean> callback, pause;
    static void require(boolean value, String label) {
        if (!value) throw new AssertionError(label);
    }
    static void expect(Object entity, boolean expected, String label) {
        require(Boolean.valueOf(expected).equals(callback.apply(entity)), label + " vanilla");
        require(Boolean.valueOf(expected).equals(pause.apply(entity)), label + " pause");
    }
    static void bypass(Object entity, String label) {
        int before = AvatarManager.lookups;
        expect(entity, false, label);
        require(before == AvatarManager.lookups, label + " performed avatar lookup");
    }
    public static void main(String[] args) {
        Minecraft mc = Minecraft.getInstance();
        // Registration must work before joining a world or loading an avatar.
        EmfCompat.init();
        callback = EMFAnimationApi.condition;
        pause = EMFAnimationApi.pauseCondition;
        require(callback != null && pause != null && AvatarManager.lookups == 0, "missing/lazily evaluated callback");
        UUID uuid = UUID.fromString("11111111-1111-1111-1111-111111111111");
        Player local = new Player(uuid);
        Player remote = new Player(UUID.fromString("22222222-2222-2222-2222-222222222222"));
        Object mob = new Object();
        bypass(null, "no player/world");
        mc.level = new Object();
        bypass(null, "no player with world");
        bypass(local, "disconnected player");
        mc.player = local;
        expect(local, false, "no avatar");
        require(AvatarManager.avatars.isEmpty(), "lookup created avatar");
        Avatar avatar = new Avatar();
        AvatarManager.avatars.put(uuid, avatar);
        AvatarManager.avatars.put(remote.getUUID(), new Avatar());
        for (boolean follow : new boolean[]{false, true, false}) {
            avatar.followVanillaPose = follow;
            expect(local, !follow, "dynamic off/on/off: " + follow);
            bypass(remote, "remote player even with loaded host-like avatar");
            bypass(mob, "mob");
            bypass(null, "null entity");
        }
        mc.level = null;
        bypass(local, "no world with local/avatar");
        mc.level = new Object();
        expect(local, true, "world restored");
        avatar.loaded = false;
        expect(local, false, "unloaded avatar");
        avatar.loaded = true;
        Object renderer = avatar.renderer;
        avatar.renderer = null;
        expect(local, false, "missing renderer");
        avatar.renderer = renderer;
        avatar.isHost = false;
        expect(local, false, "nonhost avatar");
        avatar.isHost = true;
        AvatarManager.panic = true;
        expect(local, false, "panic");
        AvatarManager.panic = false;
        expect(local, true, "panic cleared");
        Player replacement = new Player(uuid);
        mc.player = replacement;
        bypass(local, "stale player object with same UUID");
        expect(replacement, true, "replacement player same UUID");
        mc.player = null;
        bypass(replacement, "player removed after callback used");
        mc.player = replacement;
        AvatarManager.avatars.remove(uuid);
        expect(replacement, false, "avatar unload must invalidate cached decision");
        Avatar reloaded = new Avatar();
        reloaded.followVanillaPose = true;
        AvatarManager.avatars.put(uuid, reloaded);
        expect(replacement, false, "replacement avatar must not use old avatar toggle");
        reloaded.followVanillaPose = false;
        expect(replacement, true, "reloaded avatar off");
        for (int i = 0; i < 4; i++) EmfCompat.init();
        require(EMFAnimationApi.registrations == 1 && EMFAnimationApi.pauses == 1, "registration repeated");
        require(pause == EMFAnimationApi.pauseCondition, "pause callback replaced");
        require(callback == EMFAnimationApi.condition, "callback replaced");
        require(FiguraMod.LOGGER.warnings == 0, "healthy registration logged warning");
    }
}
""", "healthy")
        healthy = tmp / "healthy-classes"
        run(JDK / "javac", "--release", "25", "-cp", base_cp, "-d", healthy, fake, check)
        emf_cp = os.pathsep.join((base_cp, str(healthy)))
        run(JDK / "java", "-cp", emf_cp, "CallbackCheck")
        print("PASS: both captured callbacks without PAL; dynamic off/on/off; local-only guards; "
              "panic; same-UUID player replacement; unload/reload; registration once")

        pal = fake_pal(lambda name, text: java(name, text, "pal"))
        pal.append(java("com.zigythebird.playeranim.accessors.IAnimatedAvatar", """
package com.zigythebird.playeranim.accessors;
import com.zigythebird.playeranim.animation.AvatarAnimManager;
public interface IAnimatedAvatar {
    AvatarAnimManager playerAnimLib$getAnimManager();
}
""", "pal"))
        integration = java("IntegrationCheck", """
import java.util.UUID;
import net.minecraft.client.Minecraft;
import net.minecraft.client.Minecraft.Player;
import org.figuramc.figura.FiguraMod;
import org.figuramc.figura.avatar.*;
import org.figuramc.figura.compat.*;
import com.zigythebird.playeranim.accessors.*;
import com.zigythebird.playeranim.animation.AvatarAnimManager;
import traben.entity_model_features.EMFAnimationApi;
public class IntegrationCheck {
    // Entities implement IAnimatedAvatar, NOT the render-state IAvatarAnimationState.
    public static class AnimatedPlayer extends Player implements IAnimatedAvatar {
        public AvatarAnimManager manager = new AvatarAnimManager();
        public int calls;
        public boolean fail;
        AnimatedPlayer(UUID uuid) { super(uuid); }
        public AvatarAnimManager playerAnimLib$getAnimManager() {
            calls++;
            if (fail) throw new IllegalStateException("entity manager failure");
            return manager;
        }
    }
    public static class RenderState implements IAvatarAnimationState {
        public AvatarAnimManager playerAnimLib$getAnimManager() {
            throw new AssertionError("entity detector queried a render state");
        }
        public boolean playerAnimLib$isFirstPersonPass() { return false; }
        public void playerAnimLib$setFirstPersonPass(boolean value) {}
        public void playerAnimLib$setAnimManager(AvatarAnimManager value) {}
    }
    static void require(boolean value, String label) {
        if (!value) throw new AssertionError(label);
    }
    static void expect(Object entity, boolean vanilla, boolean pause, String label) {
        require(EMFAnimationApi.condition.apply(entity) == vanilla, label + " vanilla");
        require(EMFAnimationApi.pauseCondition.apply(entity) == pause, label + " pause");
    }
    public static void main(String[] args) throws Exception {
        Minecraft mc = Minecraft.getInstance();
        EmfCompat.init();
        UUID uuid = UUID.fromString("11111111-1111-1111-1111-111111111111");
        AnimatedPlayer local = new AnimatedPlayer(uuid);
        AnimatedPlayer remote = new AnimatedPlayer(UUID.randomUUID());
        AvatarAnimManager manager = local.manager;
        require(manager.getClass().getMethod("isActive").getDeclaringClass() != manager.getClass(),
            "fake manager must inherit isActive");
        require(PlayerAnimationCompat.isAnimatingEntity(local), "active entity not detected");
        require(!PlayerAnimationCompat.isAttackingEntity(local),
            "active general PAL animation is not an attack when combat API is absent");
        require(!PlayerAnimationCompat.isFirstPersonPass(new RenderState()), "third-person state detected");
        require(!PlayerAnimationCompat.isFirstPersonPass(null), "null first-person state detected");
        require(!PlayerAnimationCompat.isAnimatingEntity(new RenderState()), "render state detected");
        require(!PlayerAnimationCompat.isAnimatingEntity(new Object()), "non-PAL object detected");
        require(!PlayerAnimationCompat.isAnimatingEntity(null), "null detected");
        manager.active = false;
        require(!PlayerAnimationCompat.isAnimatingEntity(local), "idle entity detected");
        local.manager = null;
        require(!PlayerAnimationCompat.isAnimatingEntity(local), "null manager detected");
        local.manager = manager;
        manager.active = true;
        mc.level = new Object(); mc.player = local;
        expect(local, false, false, "active PAL without avatar");
        Avatar avatar = new Avatar(); AvatarManager.avatars.put(uuid, avatar);
        AvatarManager.avatars.put(remote.getUUID(), new Avatar());
        for (boolean follow : new boolean[]{true, false, true}) {
            avatar.followVanillaPose = follow;
            for (boolean active : new boolean[]{true, false, true}) {
                manager.active = active;
                expect(local, !follow, !follow || active, "mode=" + follow + " PAL=" + active);
                int calls = local.calls, remoteCalls = remote.calls;
                expect(remote, false, false, "remote with avatar and active PAL");
                expect(null, false, false, "null");
                expect(new Object(), false, false, "mob");
                mc.level = null; expect(local, false, false, "no world"); mc.level = new Object();
                mc.player = null; expect(local, false, false, "no player"); mc.player = local;
                AvatarManager.panic = true; expect(local, false, false, "panic"); AvatarManager.panic = false;
                avatar.loaded = false; expect(local, false, false, "unloaded"); avatar.loaded = true;
                avatar.isHost = false; expect(local, false, false, "not host"); avatar.isHost = true;
                Object renderer = avatar.renderer; avatar.renderer = null;
                expect(local, false, false, "no renderer"); avatar.renderer = renderer;
                AvatarManager.avatars.remove(uuid); expect(local, false, false, "removed avatar");
                AvatarManager.avatars.put(uuid, avatar);
                require(calls == local.calls && remoteCalls == remote.calls, "guard consulted PAL");
            }
        }
        AnimatedPlayer replacement = new AnimatedPlayer(uuid);
        mc.player = replacement;
        expect(local, false, false, "stale same-UUID player");
        expect(replacement, false, true, "replacement active player");
        replacement.manager = null; expect(replacement, false, false, "missing manager ON");
        avatar.followVanillaPose = false;
        expect(replacement, true, true, "missing manager OFF");
        mc.player = new Player(uuid); avatar.followVanillaPose = true;
        expect(mc.player, false, false, "local without optional entity interface ON");
        avatar.followVanillaPose = false;
        expect(mc.player, true, true, "local without optional entity interface OFF");
        require(manager.transformCalls == 0 && replacement.calls > 0, "detector evaluated item bones");
        require(FiguraMod.LOGGER.warnings == 0, "healthy bridge warned");
        if (!args[0].equals("healthy")) {
            mc.player = local; avatar.followVanillaPose = true;
            local.fail = args[0].equals("manager");
            manager.failure = args[0].equals("active") ? "active" : "";
            expect(local, false, false, "failing entity detection");
            require(FiguraMod.LOGGER.warnings == 1, "entity failure not logged once");
            int calls = local.calls, activeCalls = manager.activeCalls;
            local.fail = false; manager.failure = "";
            for (int i = 0; i < 3; i++) expect(local, false, false, "disabled detector");
            require(local.calls == calls && manager.activeCalls == activeCalls, "detector retried failure");
            avatar.followVanillaPose = false;
            expect(local, true, true, "OFF still isolates EMF after PAL failure");
            require(FiguraMod.LOGGER.warnings == 1, "entity failure logged repeatedly");
        }
        for (int i = 0; i < 3; i++) EmfCompat.init();
        require(EMFAnimationApi.registrations == 1 && EMFAnimationApi.pauses == 1, "registered twice");
    }
}
""", "pal")
        pal_classes = tmp / "pal-classes"
        run(JDK / "javac", "--release", "25", "-cp", emf_cp, "-d", pal_classes, *pal, integration)
        for scenario in ("healthy", "manager", "active"):
            run(JDK / "java", "-cp", os.pathsep.join((emf_cp, str(pal_classes))),
                "IntegrationCheck", scenario)
        print("PASS: both production bridges together; ON+PAL active keeps model and pauses; "
              "ON idle neither; OFF both; guarded entity access; inherited isActive; "
              "entity failures disable detection once without breaking OFF isolation")

        failures = {
            "incompatible": ("public static boolean registerVanillaModelCondition(String wrong) { return true; }",
                             "java.lang.NoSuchMethodException"),
            "throwing": ("public static boolean registerVanillaModelCondition(java.util.function.Function<Object, Boolean> f) "
                         "throws Exception { throw new Exception(\"injected registration failure\"); } "
                         "public static boolean registerPauseCondition(java.util.function.Function<Object, Boolean> f) { return true; }",
                         "java.lang.reflect.InvocationTargetException"),
            "linkage": ("static { if (Boolean.parseBoolean(\"true\")) throw new NoClassDefFoundError(\"injected missing dependency\"); }",
                        "java.lang.NoClassDefFoundError"),
        }
        for name, (body, error) in failures.items():
            broken = java(API, "package traben.entity_model_features;\n"
                          "public class EMFAnimationApi { " + body + " }", name)
            output = tmp / (name + "-classes")
            run(JDK / "javac", "--release", "25", "-d", output, broken)
            run(JDK / "java", "-cp", os.pathsep.join((base_cp, str(output))), "InitCheck", error)
        print("PASS: incompatible API, registration exception, linkage failure: no crash, warn once in fresh JVMs")
    print("Limits: stubbed Minecraft/avatar/config/panic semantics, erased fake EMF callback API; "
          "javap only for installed EMF/PAL, not actual model selection, mixins, resource packs or rendering.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        print(error.stdout or "", end="")
        print(error.stderr or "", end="")
        raise
