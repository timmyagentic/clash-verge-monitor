import assert from "node:assert/strict";
import test from "node:test";
import worker from "./worker.mjs";

test("old domain redirects with path and query intact", async () => {
  for (const path of ["/", "/guide/?from=old&x=1", "/site.css"]) {
    const response = await worker.fetch(new Request(`https://traffic-ledger.timmyagentic.si${path}`), {
      ASSETS: { fetch() { throw new Error("old domain must redirect before assets"); } },
    });
    assert.equal(response.status, 308);
    assert.equal(response.headers.get("location"), `https://clash-verge-monitor.timmyagentic.si${path}`);
  }
});

test("current domain and local preview serve assets without redirecting", async () => {
  for (const host of ["clash-verge-monitor.timmyagentic.si", "localhost:8787"]) {
    const request = new Request(`http://${host}/site.css`);
    const response = await worker.fetch(request, { ASSETS: { fetch(input) {
      assert.equal(input, request);
      return new Response("asset", { status: 200 });
    } } });
    assert.equal(response.status, 200);
    assert.equal(await response.text(), "asset");
  }
});
