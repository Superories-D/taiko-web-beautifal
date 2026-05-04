async function uploadFiles(event) {
  event.preventDefault();
  const form = document.querySelector("#upload-form");
  const submitButton = document.querySelector("#submit-button");
  const statusView = document.querySelector("#status-view");
  const errorView = document.querySelector("#error-view");

  const formData = new FormData(form);
  const uploadIndex = window.location.pathname.indexOf("/upload/");
  const basePath = uploadIndex >= 0 ? window.location.pathname.slice(0, uploadIndex + 1) : "/";
  const endpoint = `${basePath}api/upload`;

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

    const success = data && data.success === true;
    if (!success) {
      throw new Error(data.error || "Upload failed.");
    }

    statusView.textContent = "Upload complete. The song is waiting for admin review before it appears in the list.";
    form.reset();
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
