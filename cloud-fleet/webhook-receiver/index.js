const http = require("http");

const PORT = process.env.PORT || 8080;
const AIRTABLE_PAT = process.env.AIRTABLE_PAT || "";
const AIRTABLE_BASE = process.env.AIRTABLE_BASE || "appHjVD4pMobyUyNj";
const FLEET_WALLET = (
  process.env.FLEET_WALLET || "0x9e6A0CE78Bb2915d0758cc6A1cE8eA77f1B71770"
).toLowerCase();

const server = http.createServer(async (req, res) => {
  if (req.method === "GET" && req.url === "/health") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({
        status: "alive",
        wallet: FLEET_WALLET,
        timestamp: new Date().toISOString(),
      }),
    );
    return;
  }

  if (req.method === "POST" && req.url === "/webhook") {
    let body = "";
    req.on("data", (chunk) => {
      body += chunk.toString();
    });
    req.on("end", () => {
      try {
        const event = JSON.parse(body);
        console.log(
          `[${new Date().toISOString()}] Webhook received:`,
          JSON.stringify(event).slice(0, 500),
        );

        const txHash =
          event.event?.transaction?.hash || event.hash || "unknown";
        const toAddress = (
          event.event?.transaction?.to ||
          event.to ||
          ""
        ).toLowerCase();
        const amount =
          event.event?.transaction?.value || event.value || "0";

        if (toAddress === FLEET_WALLET) {
          console.log(`  Payment to fleet wallet! TX: ${txHash} Amount: ${amount}`);
        }

        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ received: true, txHash }));
      } catch (e) {
        console.error("Webhook parse error:", e.message);
        res.writeHead(400, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: e.message }));
      }
    });
    return;
  }

  res.writeHead(404);
  res.end("Not found");
});

server.listen(PORT, () => {
  console.log(`Fleet webhook receiver on :${PORT}`);
  console.log(`Monitoring wallet: ${FLEET_WALLET}`);
});
