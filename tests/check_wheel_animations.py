#!/usr/bin/env python3
"""python3 tests/check_wheel_animations.py (JDK 25; JAVA25_HOME overrides default).

Compile extracted Avatar wheel/ping/queue/run methods, Action callbacks, Animation
play/stop/pause/restart/gate/tick methods, full AnimationPlayer/TransformType,
STEP interpolation and model animation setters. Dependencies are small stubs.
Limits: no Lua interpreter, network transport/PingFunction.invoke serialization,
real clock, non-STEP interpolation, renderer or host/config policy. Echo tests call
production markActionWheelPing directly, then production runPing/consume/dispatch.
Generated sources/classes live temporarily under tests/.work, never /tmp.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "common/src/main/java/org/figuramc/figura"
JDK = Path(os.environ.get("JAVA25_HOME", "/usr/lib/jvm/java-25-openjdk")) / "bin"


def block(source, pattern):
    """Extract verbatim Java blocks; fail rather than silently test stale copies.

    ponytail: brace counting handles these snippets, not arbitrary Java literals;
    switch to a Java parser if literal/comment braces enter the selected blocks.
    """
    matches = list(re.finditer(pattern, source))
    assert len(matches) == 1, f"Expected one source block: {pattern}"
    start = matches[0].start()
    opening = source.index("{", matches[0].end())
    depth = 1
    for end in range(opening + 1, len(source)):
        depth += (source[end] == "{") - (source[end] == "}")
        if depth == 0:
            return source[start:end + 1]
    raise AssertionError(f"Unclosed source block: {pattern}")


def main():
    avatar = (SOURCE / "avatar/Avatar.java").read_text()
    action = (SOURCE / "lua/api/action_wheel/Action.java").read_text()
    animation = (SOURCE / "animation/Animation.java").read_text()
    player = (SOURCE / "animation/AnimationPlayer.java").read_text()
    transform = (SOURCE / "animation/TransformType.java").read_text()
    interpolation = (SOURCE / "animation/Interpolation.java").read_text()
    part = (SOURCE / "model/FiguraModelPart.java").read_text()
    animation_methods = "\n".join(block(animation, signature) for signature in (
        r"public boolean allowsBodyPose\(\)",
        r"public Animation play\(\)", r"public Animation stop\(\)",
        r"public Animation pause\(\)", r"public Animation restart\(\)",
        r"public Animation\(Avatar owner,[^\n]+\)",
        r"public void addAnimation\(FiguraModelPart part, AnimationChannel anim\)",
        r"public void tick\(\)",
        r"public boolean getOverrideRot\(\)",
        r"public boolean getOverridePos\(\)",
        r"public boolean getOverrideScale\(\)",
        r"public enum PlayState", r"public enum LoopMode",
        r"public record AnimationChannel\(TransformType type, Keyframe\.\.\. keyframes\)",
    ))
    part_methods = "\n".join(block(part, r"public void " + method + r"\(FiguraVec3 vec, boolean merge\)")
                             for method in ("animPosition", "animRotation", "globalAnimRot", "animScale"))
    # Preserve the actual STEP evaluator and blend math, not a fake transform.
    step = re.findall(r"^    STEP\([^\n]+;", interpolation, re.M)
    assert len(step) == 1, "STEP interpolation moved"
    interpolation_methods = "\n".join(block(interpolation, signature) for signature in (
        r"Interpolation\(IInterpolation function\)",
        r"private static FiguraVec3 getResult\(FiguraVec3 result, float strength, TransformType type\)",
        r"public FiguraVec3 generate\(Keyframe\[\] keyframes,[^\n]+\)",
        r"private interface IInterpolation",
    ))
    avatar_methods = "\n".join(block(avatar, signature) for signature in (
        r"public void runActionWheel\(Runnable callback\)",
        r"private record WheelPing\(int id, byte\[\] data\)",
        r"public synchronized void markActionWheelPing\(int id, byte\[\] data\)",
        r"private synchronized boolean consumeActionWheelPing\(int id, byte\[\] data\)",
        r"public void runPing\(int id, byte\[\] data\)",
        r"private void flushQueuedEvents\(\)",
        r"public void tickEvent\(\)",
        r"public Varargs run\(Object toRun, Instructions limit, Object\.\.\. args\)",
    ))
    action_methods = "\n".join(block(action, signature) for signature in (
        r"public void execute\(Avatar avatar, boolean left\)",
        r"private void executeCallback\(Avatar avatar, boolean left\)",
        r"public void mouseScroll\(Avatar avatar, double delta\)",
    ))
    sources = {
        "Avatar.java": """
import java.util.*;
import java.util.concurrent.ConcurrentLinkedQueue;
class Avatar {
    boolean follow = true, actionWheelCallback, scriptError, loaded = true;
    final Queue<Runnable> events = new ConcurrentLinkedQueue<>();
    final ArrayDeque<WheelPing> wheelPings = new ArrayDeque<>();
    RuntimeStub luaRuntime = new RuntimeStub();
    final Instructions tick = new Instructions();
    boolean followsVanillaPose() { return follow; }
""" + avatar_methods + "\n}",
        "Action.java": """
class Action {
    boolean toggled;
    LuaFunction leftClick, rightClick, toggle, untoggle, scroll;
""" + action_methods + "\n}",
        "AnimationPlayer.java": "import java.util.*;\n" + block(player, r"public class AnimationPlayer"),
        "TransformType.java": block(transform, r"public enum TransformType"),
        "Interpolation.java": """
public enum Interpolation {
    BEZIER((frames, current, next, strength, delta, type) -> {
        throw new AssertionError("This fixture uses STEP only");
    }),
""" + step[0] + "\nprivate final IInterpolation function;\n" + interpolation_methods + "\n}",
        "Animation.java": """
import java.util.*;
public class Animation {
    final Avatar owner;
    public final String modelName, name;
    final List<Map.Entry<FiguraModelPart, List<AnimationChannel>>> animationParts = new ArrayList<>();
    final TimeController controller = new TimeController();
    PlayState playState = PlayState.STOPPED;
    float time, lastTime, frameTime, length, blend, offset, startDelay, loopDelay;
    float speed = 1;
    boolean inverted;
    int override, priority, codeCalls;
    LoopMode loop;
    boolean actionWheelPlayback;
    void playCode(float from, float to) { codeCalls++; }
""" + animation_methods + "\n}",
        "WheelAnimationsCheck.java": """
import java.util.*;
import java.util.function.IntPredicate;
class Varargs {}
class LuaValue extends Varargs {
    final int value;
    LuaValue(int value) { this.value = value; }
}
@FunctionalInterface interface LuaFunction { void call(Object... args); }
class Instructions {}
class PingFunction {
    final LuaFunction func;
    PingFunction(LuaFunction func) { this.func = func; }
}
class Pings {
    final Map<Integer, PingFunction> functions = new HashMap<>();
    String getName(int id) { return Integer.toString(id); }
    PingFunction get(String name) { return functions.get(Integer.parseInt(name)); }
}
class RuntimeStub {
    final Pings ping = new Pings();
    int errors;
    LuaFunction tickCallback;
    Object getUser() { return this; }
    Varargs run(Object callback, Instructions limit, Object... args) {
        if (callback.equals("TICK")) callback = tickCallback;
        ((LuaFunction) callback).call(args);
        return null;
    }
    void error(Throwable error) { errors++; }
}
class PingArg {
    static LuaValue[] fromByteArray(byte[] bytes, Avatar avatar) {
        LuaValue[] values = new LuaValue[bytes.length];
        for (int i=0; i<bytes.length; i++) values[i] = new LuaValue(bytes[i]);
        return values;
    }
}
class FiguraLuaPrinter {
    static void sendPingMessage(Avatar avatar, String name, int size, LuaValue[] args) {}
}
class TimeController {
    int ticks;
    void init() {}
    void reset() {}
    void resume() {}
    void pause() {}
    void tick() { ticks++; }
    float getDiff() { return .25f; }
}
class FiguraMod {
    static int depth;
    static void pushProfiler(String name) { depth++; }
    static void popProfiler() { popProfiler(1); }
    static void popProfiler(int count) {
        depth -= count;
        if (depth < 0) throw new AssertionError("profiler underflow");
    }
}
class Mth {
    static int binarySearch(int start, int end, IntPredicate predicate) {
        // ponytail: linear lower bound for tiny fixtures; use binary search for large arrays.
        return java.util.stream.IntStream.range(start, end).filter(predicate).findFirst().orElse(end);
    }
}
class FiguraVec3 {
    double x, y, z;
    static FiguraVec3 of() { return of(0, 0, 0); }
    static FiguraVec3 of(double x, double y, double z) {
        FiguraVec3 v = new FiguraVec3(); v.x=x; v.y=y; v.z=z; return v;
    }
    FiguraVec3 copy() { return of(x, y, z); }
    FiguraVec3 add(double a, double b, double c) { x+=a; y+=b; z+=c; return this; }
    FiguraVec3 offset(double n) { return add(n, n, n); }
    FiguraVec3 scale(double n) { x*=n; y*=n; z*=n; return this; }
    void multiply(FiguraVec3 v) { x*=v.x; y*=v.y; z*=v.z; }
}
class Customization {
    FiguraVec3 pos = FiguraVec3.of(), rot = FiguraVec3.of(), scale = FiguraVec3.of(1, 1, 1);
    FiguraVec3 getAnimPos() { return pos.copy(); }
    FiguraVec3 getAnimRot() { return rot.copy(); }
    FiguraVec3 getAnimScale() { return scale.copy(); }
    void setAnimPos(double x, double y, double z) { pos = FiguraVec3.of(x,y,z); }
    void setAnimRot(double x, double y, double z) { rot = FiguraVec3.of(x,y,z); }
    void setAnimScale(double x, double y, double z) { scale = FiguraVec3.of(x,y,z); }
}
class FiguraModelPart implements Comparable<FiguraModelPart> {
    final String name;
    boolean vanillaPosePart, animated;
    int lastAnimationPriority = Integer.MIN_VALUE, animationOverride;
    final Customization customization = new Customization();
    FiguraModelPart(String name, boolean body) { this.name=name; vanillaPosePart=body; }
    public int compareTo(FiguraModelPart other) { return name.compareTo(other.name); }
""" + part_methods + """
}
record Keyframe(float time, FiguraVec3 target) {
    float getTime() { return time; }
    Interpolation getInterpolation() { return Interpolation.STEP; }
    FiguraVec3 getTargetB(float delta) { return target.copy(); }
}
public class WheelAnimationsCheck {
    static void require(boolean ok, String message) {
        if (!ok) throw new AssertionError(message);
    }
    static void vector(FiguraVec3 v, double x, double y, double z, String label) {
        require(v.x == x && v.y == y && v.z == z,
                label + ": expected " + x+","+y+","+z + " got " + v.x+","+v.y+","+v.z);
    }
    static Animation animation(Avatar owner, String name) {
        Animation a = new Animation(owner, "avatar", name, Animation.LoopMode.LOOP, false, 100, 0, 1, 0, 0);
        a.priority=5; a.override=7;
        return a;
    }
    static void ordinary(Avatar owner, Runnable callback) {
        owner.luaRuntime.tickCallback = args -> callback.run();
        owner.tickEvent();
    }
    static void drain(Avatar owner) { ordinary(owner, () -> {}); }
    static void denied(Animation a, String why) { require(!a.allowsBodyPose(), why); }
    static void allowed(Animation a, String why) { require(a.allowsBodyPose(), why); }
    static void channel(Animation a, FiguraModelPart part, TransformType type) {
        a.addAnimation(part, new Animation.AnimationChannel(type,
                new Keyframe(0, FiguraVec3.of(2,4,6))));
    }
    static void channels(Animation a, FiguraModelPart part) {
        for (TransformType type : List.of(TransformType.POSITION, TransformType.ROTATION, TransformType.SCALE))
            channel(a, part, type);
    }
    static void tick(Animation a, int expectedCost) {
        require(AnimationPlayer.tick(a, 20) == 20-expectedCost, "channel budget: " + a.name);
        require(FiguraMod.depth == 0, "unbalanced profiler: " + a.name);
    }
    static void neutral(FiguraModelPart p) {
        vector(p.customization.pos, 0,0,0, p.name + " position neutral");
        vector(p.customization.rot, 0,0,0, p.name + " rotation neutral");
        vector(p.customization.scale, 1,1,1, p.name + " scale neutral");
        require(!p.animated && p.lastAnimationPriority == Integer.MIN_VALUE && p.animationOverride == 0,
                p.name + " neutral bookkeeping");
    }
    static void contribution(FiguraModelPart p, double blend, int priority, int override) {
        vector(p.customization.pos, -2*blend,4*blend,6*blend, p.name + " position");
        vector(p.customization.rot, -2*blend,-4*blend,6*blend, p.name + " rotation");
        vector(p.customization.scale, 1+blend,1+3*blend,1+5*blend, p.name + " scale");
        require(p.animated && p.lastAnimationPriority == priority && p.animationOverride == override,
                p.name + " contribution bookkeeping / override bits");
    }
    static void gatesAndCallbacks() {
        for (String name : List.of("walk", "run", "idle", "wave", "Wave", "anything", "avatar.walk", "")) {
            Avatar owner = new Avatar();
            Animation clip = animation(owner, name);
            ordinary(owner, clip::play);
            denied(clip, "ordinary tick start: " + name);
            Action action = new Action();
            action.leftClick = args -> clip.play();
            action.execute(owner, true);
            allowed(clip, "direct radial click (including already playing): " + name);
            require(!owner.actionWheelCallback, "direct click scope leaked");
            ordinary(owner, clip::play);
            allowed(clip, "ordinary repeated play must preserve wheel provenance");
            clip.pause(); allowed(clip, "paused action remains allowed");
            ordinary(owner, clip::play); allowed(clip, "resume preserves wheel provenance");
            clip.loop = Animation.LoopMode.HOLD; clip.length=.25f; clip.tick();
            require(clip.playState == Animation.PlayState.HOLDING, "reach HOLD naturally");
            allowed(clip, "held action remains allowed");
            for (float blend : new float[]{0, -0f, .5f, 1, -1}) {
                clip.blend=blend;
                require(clip.allowsBodyPose() == (blend != 0), "blend gate " + blend);
            }
            clip.blend=1;
            clip.stop(); denied(clip, "stop clears wheel provenance");
            ordinary(owner, clip::play); denied(clip, "ordinary restart after stop");
            owner.runActionWheel(clip::restart); allowed(clip, "wheel restart");
            ordinary(owner, clip::restart); denied(clip, "ordinary restart clears provenance");
            owner.follow=false; clip.blend=0; allowed(clip, "follow disabled bypass");
        }
        // Exercise actual Action.execute selection, toggle arguments and fallback.
        for (boolean queued : List.of(false, true)) {
            Avatar owner = new Avatar();
            Animation clip = animation(owner, "walk");
            int[] clicks = {0}, toggles = {0};
            List<String> callbacks = new ArrayList<>();
            owner.luaRuntime.ping.functions.put(1, new PingFunction(args -> clip.play()));
            Runnable start = () -> {
                require(owner.actionWheelCallback, "callback must be in wheel scope");
                if (queued) owner.runPing(1, new byte[]{42}); else clip.play();
            };
            Action action = new Action();
            action.leftClick = args -> { callbacks.add("left"); clicks[0]++; start.run(); };
            action.rightClick = args -> { callbacks.add("right"); clicks[0]++; start.run(); };
            action.toggle = args -> { callbacks.add("toggle"); toggles[0]++; require((boolean)args[0] == action.toggled, "toggle argument"); start.run(); };
            action.untoggle = args -> { callbacks.add("untoggle"); toggles[0]++; require(!(boolean)args[0], "untoggle argument"); start.run(); };
            action.execute(owner,true); drain(owner); allowed(clip, "left click/toggle start");
            require(action.toggled && clicks[0]==1 && toggles[0]==1, "left toggles on");
            clip.stop(); action.execute(owner,false); drain(owner); allowed(clip, "right click start");
            require(action.toggled && clicks[0]==2 && toggles[0]==1, "right must not toggle");
            clip.stop(); action.execute(owner,true); drain(owner); allowed(clip, "untoggle start");
            require(!action.toggled && toggles[0]==2, "untoggle callback");
            action.leftClick=null;
            clip.stop(); action.execute(owner,true); drain(owner); allowed(clip, "toggle-only start");
            action.untoggle=null;
            clip.stop(); action.execute(owner,true); drain(owner); allowed(clip, "toggle fallback on untoggle");
            require(!action.toggled && toggles[0]==4, "fallback toggles off");
            require(callbacks.equals(List.of("left","toggle","right","left","untoggle","toggle","toggle")),
                    "correct click/toggle callback selection and order");
            action.scroll=args -> { require((double)args[0]==-2, "scroll delta"); start.run(); };
            clip.stop(); action.mouseScroll(owner,-2); drain(owner); allowed(clip, "scroll start");
            require(!owner.actionWheelCallback, "callback/ping scope leaked");
            clip.stop(); ordinary(owner,clip::play); denied(clip, "next ordinary tick denied");
        }
    }
    static void scopesAndQueuedPings() {
        Avatar owner = new Avatar();
        Animation clip = animation(owner, "idle");
        owner.runActionWheel(() -> {
            require(owner.actionWheelCallback, "outer scope");
            owner.runActionWheel(() -> require(owner.actionWheelCallback, "nested scope"));
            require(owner.actionWheelCallback, "nested scope restored outer");
            try { owner.runActionWheel(() -> { throw new IllegalStateException("expected"); }); }
            catch (IllegalStateException expected) {}
            require(owner.actionWheelCallback, "nested exception restored outer");
        });
        require(!owner.actionWheelCallback, "outer scope reset");
        Action action = new Action();
        action.rightClick=args -> { throw new IllegalStateException("expected"); };
        try { action.execute(owner,false); throw new AssertionError("callback should throw"); }
        catch (IllegalStateException expected) {}
        require(!owner.actionWheelCallback, "exception resets Action scope");
        owner.luaRuntime.ping.functions.put(1, new PingFunction(args -> clip.play()));
        owner.runActionWheel(() -> owner.runPing(1,new byte[]{1}));
        require(!owner.actionWheelCallback && clip.playState==Animation.PlayState.STOPPED,
                "queued ping deferred beyond originating wheel scope");
        drain(owner); allowed(clip, "queued local wheel ping");
        clip.stop(); owner.runPing(1,new byte[]{1}); drain(owner); denied(clip, "ordinary queued ping");
        owner.luaRuntime.ping.functions.put(2, new PingFunction(args -> {
            require(owner.actionWheelCallback, "throwing ping provenance");
            throw new IllegalStateException("expected");
        }));
        owner.runActionWheel(() -> owner.runPing(2,new byte[]{2}));
        drain(owner);
        require(owner.luaRuntime.errors==1 && !owner.actionWheelCallback, "queued exception reset");
        clip.stop(); ordinary(owner,clip::play); denied(clip, "tick after throwing ping");
        owner.luaRuntime.ping.functions.put(3, new PingFunction(args -> owner.runPing(1,new byte[]{1})));
        owner.runActionWheel(() -> owner.runPing(3,new byte[]{3}));
        drain(owner); allowed(clip, "nested queued local ping provenance");
        require(!owner.actionWheelCallback, "nested queued scopes reset");
    }
    static void echoes() {
        Avatar owner = new Avatar();
        Animation clip = animation(owner,"run");
        List<Integer> payloads = new ArrayList<>();
        LuaFunction callback=args -> { payloads.add(((LuaValue)args[0]).value); clip.play(); };
        owner.luaRuntime.ping.functions.put(7,new PingFunction(callback));
        owner.luaRuntime.ping.functions.put(8,new PingFunction(callback));
        byte[] sent = {11,22};
        owner.markActionWheelPing(7,sent);
        sent[0]=99; // marker owns a clone, not the caller's mutable buffer
        owner.runPing(8,new byte[]{11,22}); drain(owner); denied(clip,"echo wrong id");
        clip.stop(); owner.runPing(7,new byte[]{11,23}); drain(owner); denied(clip,"echo wrong payload");
        clip.stop(); owner.runPing(7,new byte[]{11}); drain(owner); denied(clip,"echo wrong length");
        clip.stop(); owner.runPing(7,new byte[]{99,22}); drain(owner); denied(clip,"marker clones payload");
        clip.stop(); owner.runPing(7,new byte[]{11,22});
        require(!owner.actionWheelCallback, "echo scope only at dispatch");
        drain(owner); allowed(clip,"matching id and payload echo");
        clip.stop(); owner.runPing(7,new byte[]{11,22}); drain(owner); denied(clip,"echo consumed once");
        require(payloads.equals(List.of(11,11,11,99,11,11)), "all ping payloads actually dispatched");
        // Consumption is at enqueue, not dispatch: two pending identical echoes admit only one.
        List<Boolean> provenance = new ArrayList<>();
        owner.luaRuntime.ping.functions.put(9,new PingFunction(args -> provenance.add(owner.actionWheelCallback)));
        owner.markActionWheelPing(9,new byte[]{3});
        owner.runPing(9,new byte[]{3}); owner.runPing(9,new byte[]{3}); drain(owner);
        require(provenance.equals(List.of(true,false)), "one marker cannot admit two pending echoes");
        Avatar other = new Avatar();
        other.luaRuntime.ping.functions.put(7,new PingFunction(args -> require(!other.actionWheelCallback,"avatar isolation")));
        owner.markActionWheelPing(7,new byte[]{5});
        other.runPing(7,new byte[]{5}); drain(other);
        clip.stop(); owner.runPing(7,new byte[]{5}); drain(owner); allowed(clip,"other avatar cannot consume marker");
        // Out-of-order matches must not drop unrelated markers; duplicates count individually.
        owner.markActionWheelPing(7,new byte[]{1});
        owner.markActionWheelPing(7,new byte[]{2});
        owner.markActionWheelPing(7,new byte[]{1});
        for (int value : new int[]{2,1,1}) {
            clip.stop(); owner.runPing(7,new byte[]{(byte)value}); drain(owner);
            allowed(clip,"out-of-order/duplicate marker");
        }
        clip.stop(); owner.runPing(7,new byte[]{1}); drain(owner); denied(clip,"duplicate markers exhausted");
        for (int i=0; i<129; i++) owner.markActionWheelPing(7,new byte[]{(byte)i});
        clip.stop(); owner.runPing(7,new byte[]{0}); drain(owner); denied(clip,"oldest marker evicted at bound");
        clip.stop(); owner.runPing(7,new byte[]{1}); drain(owner); allowed(clip,"next marker retained at bound");
        clip.stop(); owner.runPing(7,new byte[]{(byte)128}); drain(owner); allowed(clip,"newest marker retained");
        require(!owner.actionWheelCallback,"echo scope reset");
    }
    static void playerFiltering() {
        for (boolean follow : List.of(false,true))
        for (boolean wheel : List.of(false,true))
        for (String name : List.of("walk","run","idle","wave","anything"))
        for (float blend : new float[]{0,.5f,1}) {
            Avatar owner = new Avatar(); owner.follow=follow;
            Animation clip=animation(owner,name); clip.blend=blend;
            FiguraModelPart body=new FiguraModelPart("body",true), hair=new FiguraModelPart("hair",false);
            channels(clip,body); channels(clip,hair);
            if (wheel) owner.runActionWheel(clip::play); else ordinary(owner,clip::play);
            boolean allow=!follow || (wheel && blend!=0);
            tick(clip,allow?6:3);
            require(clip.controller.ticks==1 && clip.frameTime==.25f && clip.codeCalls==1,
                    "denied body still advances animation clock and code dispatch");
            if (allow) contribution(body,blend,5,7); else neutral(body);
            contribution(hair,blend,5,7);
            AnimationPlayer.clear(clip); neutral(body); neutral(hair);
            clip.pause(); tick(clip,allow?6:3);
            require(clip.controller.ticks==1,"paused clock must not tick");
            if (allow) contribution(body,blend,5,7); else neutral(body);
            contribution(hair,blend,5,7);
            clip.stop(); AnimationPlayer.clear(clip); neutral(body); neutral(hair);
            tick(clip,0); neutral(body); neutral(hair);
        }
        Avatar owner=new Avatar();
        FiguraModelPart body=new FiguraModelPart("body",true);
        Animation denied=animation(owner,"walk"); denied.priority=99; channels(denied,body); denied.play();
        Animation action=animation(owner,"walk"); channels(action,body); owner.runActionWheel(action::play);
        tick(denied,0); neutral(body); tick(action,3); contribution(body,1,5,7);
        tick(denied,0); contribution(body,1,5,7);
        AnimationPlayer.clear(action); neutral(body);
    }
    public static void main(String[] args) {
        gatesAndCallbacks(); scopesAndQueuedPings(); echoes(); playerFiltering();
        System.out.println("PASS: extracted wheel/Action callbacks, local queued pings, one-shot id+payload echoes; " +
                "nesting/exception reset; play/stop/restart/pause/HOLD/blend/no-name gate; " +
                "AnimationPlayer body filtering, accessories, clocks, overrides, priority and clear");
    }
}
""",
    }
    work = ROOT / "tests/.work"
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wheel-animations-", dir=work) as directory:
        paths = []
        for name, source in sources.items():
            path = Path(directory) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
            paths.append(str(path))
        subprocess.run([str(JDK / "javac"), "--release", "25", "-d", directory, *paths], check=True)
        subprocess.run([str(JDK / "java"), "-cp", directory, "WheelAnimationsCheck"], check=True)


if __name__ == "__main__":
    main()
