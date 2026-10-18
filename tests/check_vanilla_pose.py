#!/usr/bin/env python3
"""python3 tests/check_vanilla_pose.py (JDK 25; JAVA25_HOME overrides the default).

Compiles production pose/constructor/accessor/copy methods, renderer scopes and
callback guards, and Avatar's gate. Only dependency types and renderer bodies are
stubbed. No Gradle artifacts, game, libraries, or test framework are required.
Limits: no matrix math, GPU rendering, Lua runtime, resource-pack integration, or
full renderer traversal; callback blocks run in a small instrumented delegate.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "common/src/main/java/org/figuramc/figura"
JDK = Path(os.environ.get("JAVA25_HOME", "/usr/lib/jvm/java-25-openjdk")) / "bin"


def block(source, pattern):
    """Extract one balanced Java block, failing closed if its signature moves.

    ponytail: brace counting is sufficient for these snippets (no literal/comment
    braces); use a Java parser if the extracted methods acquire such content.
    """
    matches = list(re.finditer(pattern, source))
    assert len(matches) == 1, f"Expected one source block: {pattern}"
    start = matches[0].start()
    opening = source.index("{", matches[0].start())
    depth = 1
    for end in range(opening + 1, len(source)):
        depth += (source[end] == "{") - (source[end] == "}")
        if depth == 0:
            return source[start:end + 1]
    raise AssertionError(f"Unclosed source block: {pattern}")


def main():
    part = (SOURCE / "model/FiguraModelPart.java").read_text()
    custom = (SOURCE / "model/PartCustomization.java").read_text()
    renderer = (SOURCE / "model/rendering/ImmediateFiguraRenderer.java").read_text()
    avatar = (SOURCE / "avatar/Avatar.java").read_text()
    config = (SOURCE / "config/Configs.java").read_text()
    assert re.search(r'FOLLOW_VANILLA_POSE\s*=\s*new ConfigType.BoolConfig\(\s*'
                     r'"follow_vanilla_pose"\s*,\s*RENDERING\s*,\s*false\s*\)', config), \
        "Follow pose must default to false in the actual config"
    lang = json.loads((ROOT / "common/src/main/resources/assets/figura/lang/en_us.json").read_text())
    for key in ("figura.config.follow_vanilla_pose", "figura.config.follow_vanilla_pose.tooltip"):
        assert isinstance(lang.get(key), str) and lang[key].strip(), f"Missing label: {key}"

    # Keep real fields, setters/getters and copyTo: a fake copy implementation
    # could hide the very live-state aliasing regression this check targets.
    customization = custom[custom.index("public class PartCustomization"):
                           custom.index("    public void applyToStack")]
    customization += custom[custom.index("    public void setPos("):
                            custom.index("    public void setMatrix(")]
    customization += custom[custom.index("    public void setPrimaryRenderType("):
                            custom.index("    // Modify this object")]
    customization += "\n}"
    customization = customization.replace("public class PartCustomization", "class PartCustomization", 1)
    fields = []
    for name in ("customization", "bindPose", "parentType", "bindParentType",
                 "playerCustomization", "animationOverride", "vanillaPosePart"):
        matches = re.findall(r"^    (?:public|private) [^\n;]*\b" + name + r"(?:\s*=[^;]*)?;", part, re.M)
        assert len(matches) == 1, f"Field moved: {name}"
        fields.append(matches[0])
    constructor = block(part, r"public FiguraModelPart\(\s*Avatar owner,\s*String name,\s*"
                        r"PartCustomization customization,\s*Map<Integer, List<Vertex>> vertices,\s*"
                        r"List<FiguraModelPart> children,\s*byte formatVersion\s*\)")
    callbacks = "\n".join(block(renderer, r"if \([^\n]*part\." + callback + r" != null\)\s*\{")
                          for callback in ("preRender", "midRender", "postRender"))
    java = """
import java.util.*;
class FiguraVec3 {
    double x, y, z;
    static FiguraVec3 of() { return of(0, 0, 0); }
    static FiguraVec3 of(double x, double y, double z) {
        FiguraVec3 v = new FiguraVec3(); v.set(x, y, z); return v;
    }
    void set(double x, double y, double z) { this.x=x; this.y=y; this.z=z; }
    void set(FiguraVec3 v) { set(v.x, v.y, v.z); }
    void add(double x, double y, double z) { set(this.x+x, this.y+y, this.z+z); }
    FiguraVec3 copy() { return of(x, y, z); }
}
// Matrix storage only: actual matrix calculations are outside this check.
class FiguraMat3 {
    int marker;
    static FiguraMat3 of() { return new FiguraMat3(); }
    void set(FiguraMat3 m) { marker = m.marker; }
}
class FiguraMat4 {
    int marker;
    static FiguraMat4 of() { return new FiguraMat4(); }
    void set(FiguraMat4 m) { marker = m.marker; }
}
enum PartType { GROUP, MESH }
enum FiguraRenderTypes { PRIMARY, SECONDARY }
class TextureCustomization {}
class Vertex {}
enum ParentType {
    None(false), Head(false), Body(false), LeftArm(false), RightArm(false), LeftLeg(false), RightLeg(false), World(true);
    final boolean isSeparate;
    ParentType(boolean separate) { isSeparate = separate; }
}
class Configs {
    static class BoolConfig { boolean value; }
    static final BoolConfig FOLLOW_VANILLA_POSE = new BoolConfig();
}
class FiguraMod { static void popPushProfiler(String ignored) {} }
class Avatar {
    boolean isHost;
    Object render;
    enum Mode { RENDER }
    Mode renderMode = Mode.RENDER;
    final List<String> calls = new ArrayList<>();
    void run(String callback, Object event, float delta, String mode, FiguraModelPart part) {
        calls.add(callback);
    }
""" + block(avatar, r"public boolean followsVanillaPose\(\)") + "\n}\n" + customization + """
class FiguraModelPart {
    Avatar owner;
    String name;
    Map<Integer, List<Vertex>> vertices;
    List<FiguraModelPart> children;
    byte formatVersion;
    String preRender = "pre", midRender = "mid", postRender = "post";
""" + "\n".join(fields) + constructor + block(part, r"public void markVanillaPoseParts\(\)") + block(part, r"public PartCustomization createVanillaPose\(\)") + """
}
class Renderer {
    final Avatar avatar = new Avatar();
    static class Scheme { ParentType parentType = ParentType.None; }
    final Scheme currentFilterScheme = new Scheme();
    float tickDelta;
    boolean expectedFollow, fail;
    int visits;
    PartCustomization live;
    static final RuntimeException FAILURE = new RuntimeException("injected renderer failure");
""" + block(renderer, r"private VanillaPose vanillaPose\(FiguraModelPart part\)") + block(
        renderer, r"private static final class VanillaPose implements AutoCloseable") + block(
        renderer, r"protected boolean renderPart\(FiguraModelPart part, int\[\] remainingComplexity, boolean prevPredicate\)") + block(
        renderer, r"protected void calculatePartMatrices\(FiguraModelPart part\)") + """
    void checkSeparateParent(FiguraModelPart part) {
        ParentType original = part.parentType;
        try (VanillaPose pose = new VanillaPose(part)) {
            VanillaPoseCheck.require(part.parentType == original, "separate membership changed");
        }
        VanillaPoseCheck.require(part.parentType == original, "separate parent not restored");
    }
    // Instrument the delegates, not the real wrapper/cleanup/gating logic.
    private boolean renderPart(FiguraModelPart part, int[] budget, boolean previous, boolean followPose) {
        VanillaPoseCheck.require(followPose == expectedFollow, "delegate follow flag");
        visit(part);
""" + callbacks + """
        if (fail) throw FAILURE;
        return false;
    }
    private void calculatePartMatricesForPose(FiguraModelPart part) {
        visit(part);
        if (fail) throw FAILURE;
    }
    private void visit(FiguraModelPart part) {
        visits++;
        VanillaPoseCheck.require((part.customization != live) == expectedFollow, "scope selection");
        if (expectedFollow) {
            VanillaPoseCheck.pose(part.customization, live);
            VanillaPoseCheck.require(part.parentType == ParentType.Head && part.animationOverride == 0,
                                     "temporary parent / animation override");
            // Emulate vanilla rendering overwriting its scratch customization.
            part.playerCustomization = new PartCustomization();
            part.parentType = ParentType.None;
            part.animationOverride = 99;
            VanillaPoseCheck.channels(part.customization, 100);
            part.customization.color.set(9, 9, 9);
            part.customization.uvMatrix.marker = 99;
        } else {
            VanillaPoseCheck.require(part.parentType == ParentType.Body && part.animationOverride == 7,
                                     "bypass changed part state");
        }
    }
}
public class VanillaPoseCheck {
    static void require(boolean ok, String message) {
        if (!ok) throw new AssertionError(message);
    }
    static void equal(FiguraVec3 v, double n) {
        require(v.x == n && v.y == n+1 && v.z == n+2, "vector != " + n + ": " + v.x+","+v.y+","+v.z);
    }
    static void channels(PartCustomization p, double n) {
        p.setPos(n,n+1,n+2); p.setRot(n+3,n+4,n+5);
        p.setScale(n+6,n+7,n+8); p.setPivot(n+9,n+10,n+11);
        p.offsetPos(n+12,n+13,n+14); p.offsetRot(n+15,n+16,n+17);
        p.offsetScale(n+18,n+19,n+20); p.offsetPivot(n+21,n+22,n+23);
    }
    static void transforms(PartCustomization p, double n) {
        equal(p.getPos(),n); equal(p.getRot(),n+3); equal(p.getScale(),n+6); equal(p.getPivot(),n+9);
        equal(p.getOffsetPos(),n+12); equal(p.getOffsetRot(),n+15);
        equal(p.getOffsetScale(),n+18); equal(p.getOffsetPivot(),n+21);
    }
    static void appearance(PartCustomization p, PartCustomization live) {
        equal(p.color, .25); equal(p.color2, .5);
        require(!p.visible && Boolean.FALSE.equals(p.vanillaVisible), "visibility");
        require(p.alpha == .5f && p.light == 123 && p.overlay == 456, "alpha/light/overlay");
        require(p.primaryTexture == live.primaryTexture && p.secondaryTexture == live.secondaryTexture,
                "texture identity");
        require(p.getPrimaryRenderType() == FiguraRenderTypes.PRIMARY &&
                p.getSecondaryRenderType() == FiguraRenderTypes.SECONDARY, "render types");
        require(p.uvMatrix.marker == 42 && p.partType == PartType.MESH, "UV / geometry type");
    }
    static void pose(PartCustomization p, PartCustomization live) {
        transforms(p, 2);
        for (FiguraVec3 v : List.of(p.getAnimPos(), p.getAnimRot()))
            require(v.x == 0 && v.y == 0 && v.z == 0, "animation position/rotation not cleared");
        FiguraVec3 scale = p.getAnimScale();
        require(scale.x == 1 && scale.y == 1 && scale.z == 1, "animation scale not reset");
        appearance(p, live);
        require(p.needsMatrixRecalculation, "stale transform matrix");
    }
    static void live(PartCustomization p) {
        transforms(p, 30);
        equal(p.getAnimPos(), 3); equal(p.getAnimRot(), 6); equal(p.getAnimScale(), 9);
        appearance(p, p);
        require(!p.needsMatrixRecalculation && p.positionMatrix.marker == 73, "live matrix state changed");
    }
    static FiguraModelPart node(ParentType type, FiguraModelPart... children) {
        FiguraModelPart p = new FiguraModelPart(null, "part", new PartCustomization(),
            new HashMap<>(), Arrays.asList(children), (byte)0);
        p.bindParentType = type;
        p.markVanillaPoseParts();
        return p;
    }
    public static void main(String[] args) {
        PartCustomization live = new PartCustomization();
        channels(live, 2);
        FiguraModelPart part = new FiguraModelPart(null, "part", live, new HashMap<>(), new ArrayList<>(), (byte)0);
        part.parentType = ParentType.Body; part.bindParentType = ParentType.Head;
        part.animationOverride = 7;
        channels(live, 30);
        live.setAnimPos(3,4,5); live.setAnimRot(6,7,8); live.setAnimScale(9,10,11);
        live.visible = false; live.vanillaVisible = false;
        live.color.set(.25,1.25,2.25); live.color2.set(.5,1.5,2.5);
        live.alpha = .5f; live.light = 123; live.overlay = 456;
        live.primaryTexture = new TextureCustomization(); live.secondaryTexture = new TextureCustomization();
        live.setPrimaryRenderType(FiguraRenderTypes.PRIMARY); live.setSecondaryRenderType(FiguraRenderTypes.SECONDARY);
        live.uvMatrix.marker = 42; live.positionMatrix.marker = 73; live.partType = PartType.MESH;
        live.needsMatrixRecalculation = false;
        PartCustomization pose = part.createVanillaPose();
        pose(pose, live);
        require(pose != live && part.customization == live, "createVanillaPose changed live reference");
        channels(pose, 100); pose.color.set(9,9,9); pose.uvMatrix.marker = 99;
        live(live); pose(part.createVanillaPose(), live); // neither live nor bind data aliased

        Renderer renderer = new Renderer(); renderer.live = live;
        for (boolean bodyRig : List.of(false, true))
        for (boolean host : List.of(false, true))
        for (boolean enabled : List.of(false, true))
        for (boolean separate : List.of(false, true))
        for (boolean matrices : List.of(false, true))
        for (boolean fail : List.of(false, true))
        for (boolean savedPlayer : List.of(false, true)) {
            renderer.avatar.isHost = host;
            Configs.FOLLOW_VANILLA_POSE.value = enabled;
            require(renderer.avatar.followsVanillaPose() == (host && enabled), "host/config gate");
            renderer.currentFilterScheme.parentType = separate ? ParentType.World : ParentType.None;
            part.vanillaPosePart = bodyRig;
            renderer.expectedFollow = host && enabled && !separate && bodyRig;
            renderer.fail = fail;
            renderer.avatar.calls.clear();
            PartCustomization player = savedPlayer ? new PartCustomization() : null;
            part.playerCustomization = player;
            int before = renderer.visits;
            try {
                if (matrices) renderer.calculatePartMatrices(part);
                else require(!renderer.renderPart(part, new int[]{100}, true), "return value lost");
                require(!fail, "expected injected failure");
            } catch (RuntimeException error) {
                require(fail && error == Renderer.FAILURE, "exception swallowed/replaced");
            }
            require(renderer.visits == before+1, "delegate not called exactly once");
            require(part.customization == live && part.parentType == ParentType.Body &&
                    part.animationOverride == 7 && part.playerCustomization == player, "scope did not restore state");
            live(live);
            List<String> expected = matrices || renderer.expectedFollow ? List.of() : List.of("pre", "mid", "post");
            require(renderer.avatar.calls.equals(expected), "callback gate: " + renderer.avatar.calls);
        }
        // Real imported hierarchy: root -> UpperBody -> Head -> Hair -> physics chain.
        FiguraModelPart hairTip = node(ParentType.None);
        FiguraModelPart hair = node(ParentType.None, hairTip);
        FiguraModelPart head = node(ParentType.Head, hair);
        FiguraModelPart upper = node(ParentType.None, head);
        FiguraModelPart leg = node(ParentType.LeftLeg);
        FiguraModelPart root = node(ParentType.None, upper, leg);
        require(root.vanillaPosePart && upper.vanillaPosePart && head.vanillaPosePart && leg.vanillaPosePart,
                "body bones and ancestors must follow vanilla");
        require(!hair.vanillaPosePart && !hairTip.vanillaPosePart,
                "physics branches must keep live transforms/callbacks");
        // Script changes across separate-pass boundaries must keep live index membership.
        for (ParentType[] pair : List.of(new ParentType[]{ParentType.World, ParentType.Head},
                                        new ParentType[]{ParentType.Body, ParentType.World})) {
            part.parentType = pair[0]; part.bindParentType = pair[1];
            renderer.checkSeparateParent(part);
        }
        System.out.println("PASS: bind transforms, appearance, cleared animation, live-state isolation; " +
            "both scopes restore on success/exception; host/toggle/separate bypass; pre/mid/post callback gates");
    }
}
"""
    work = ROOT / "tests/.work"
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vanilla-pose-", dir=work) as directory:
        path = Path(directory) / "VanillaPoseCheck.java"
        path.write_text(java)
        subprocess.run([str(JDK / "javac"), "--release", "25", "-d", directory, str(path)], check=True)
        subprocess.run([str(JDK / "java"), "-cp", directory, "VanillaPoseCheck"], check=True)
    print("PASS: actual config defaults off; English label and tooltip present")


if __name__ == "__main__":
    main()
