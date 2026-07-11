async function uploadFiles(event) {
  event.preventDefault();
  const form = document.querySelector("#upload-form");
  const submitButton = document.querySelector("#submit-button");
  const statusView = document.querySelector("#status-view");
  const errorView = document.querySelector("#error-view");

  const formData = new FormData(form);
  const endpoint = "../api/user-upload";

  errorView.textContent = "";
  statusView.textContent = "Uploading...";
  submitButton.disabled = true;
  let timeout = null;

  try {
    const tokenResponse = await fetch("../api/csrftoken", {cache: "no-store"});
    if (!tokenResponse.ok) throw new Error(`HTTP ${tokenResponse.status}`);
    const tokenData = await tokenResponse.json();
    if (tokenData.status !== "ok" || !tokenData.token) throw new Error("Could not start a secure upload.");
    const controller = new AbortController();
    timeout = setTimeout(() => controller.abort(), 120000);
    const res = await fetch(endpoint, {
      method: "POST",
      headers: {"X-CSRFToken": tokenData.token},
      signal: controller.signal,
      body: formData
    });

    const rawText = await res.text();
    clearTimeout(timeout);
    let data = null;
    try {
      data = rawText ? JSON.parse(rawText) : null;
    } catch (_err) {
      data = { message: rawText };
    }

    if (!res.ok) {
      throw new Error((data && (data.error || data.message)) || `HTTP ${res.status}`);
    }

    const success = !data || data.success !== false;
    if (!success) {
      throw new Error(data.error || "Upload failed.");
    }

    statusView.textContent = "Upload complete. It may take a moment before the song appears in the list.";
    form.reset();
  } catch (error) {
    if (timeout) clearTimeout(timeout);
    statusView.textContent = "Upload failed.";
    errorView.textContent = String(error);
  } finally {
    if (timeout) clearTimeout(timeout);
    submitButton.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelector("#upload-form").addEventListener("submit", uploadFiles);
});
