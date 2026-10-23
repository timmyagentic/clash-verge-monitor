const LEGACY_HOST = "traffic-ledger.timmyagentic.si";
const CURRENT_HOST = "clash-verge-monitor.timmyagentic.si";

export default {
  fetch(request, env) {
    const url = new URL(request.url);
    if (url.hostname === LEGACY_HOST) {
      url.protocol = "https:";
      url.host = CURRENT_HOST;
      return Response.redirect(url.toString(), 308);
    }
    return env.ASSETS.fetch(request);
  },
};
