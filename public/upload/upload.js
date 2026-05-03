async function uploadFiles(event) {
  event.preventDefault();
  const form = document.querySelector("#upload-form");
  const submitButton = document.querySelector("#submit-button");
  const statusView = document.querySelector("#status-view");
  const errorView = document.querySelector("#error-view");

  const formData = new FormData(form);
  const endpoint = (formData.get("api_endpoint") || "").toString().trim();
  formData.delete("api_endpoint");

  errorView.textContent = "";
  statusView.textContent = "Uploading...";
  submitButton.disabled = true;

  try {
    const res = await fetch(endpoint, {
      method: "POST",
      body: formData
    });

    const rawText = await res.text();
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
    document.querySelector("#api_endpoint").value = endpoint || "/api/upload";
  } catch (error) {
    statusView.textContent = "Upload failed.";
    errorView.textContent = String(error);
  } finally {
    submitButton.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelector("#upload-form").addEventListener("submit", uploadFiles);
});
