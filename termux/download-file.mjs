import { createWriteStream, promises as fs } from "node:fs";
import { get } from "node:https";
import { pipeline } from "node:stream/promises";

const [, , sourceUrl, destination] = process.argv;

if (!sourceUrl || !destination) {
  console.error("Usage: node download-file.mjs URL DESTINATION");
  process.exit(2);
}

const partial = `${destination}.part`;

async function download(url, redirectsLeft = 10) {
  const response = await new Promise((resolve, reject) => {
    const request = get(url, resolve);
    request.on("error", reject);
  });

  if (
    response.statusCode >= 300 &&
    response.statusCode < 400 &&
    response.headers.location
  ) {
    response.resume();
    if (redirectsLeft === 0) throw new Error("Too many download redirects");
    return download(new URL(response.headers.location, url), redirectsLeft - 1);
  }

  if (response.statusCode !== 200) {
    response.resume();
    throw new Error(`Download failed with HTTP ${response.statusCode}`);
  }

  await pipeline(response, createWriteStream(partial));
}

let lastError;
for (let attempt = 1; attempt <= 3; attempt += 1) {
  try {
    await fs.rm(partial, { force: true });
    await download(sourceUrl);
    await fs.rename(partial, destination);
    console.log(`Downloaded: ${destination}`);
    process.exit(0);
  } catch (error) {
    lastError = error;
    await fs.rm(partial, { force: true });
    if (attempt < 3) console.error(`Download attempt ${attempt} failed; retrying...`);
  }
}

console.error(lastError instanceof Error ? lastError.message : String(lastError));
process.exit(1);
