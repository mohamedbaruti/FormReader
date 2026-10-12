package com.formreader.nidaenrol;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.ContentValues;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.view.ViewGroup;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.io.File;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;

/**
 * NIDA Enrolment: the Form Reader running entirely on the phone (no computer, no internet needed).
 *
 * The reader (Python, OpenCV, the character models, the form editions and the rules: the same as
 * on the computer, without Reader Training) is started inside the app and listens only on the
 * phone itself (127.0.0.1). This activity shows its screens full screen and adds:
 *   - "Take photo" opens the camera (the photo is also kept in Pictures/NIDA Enrolment),
 *     "Choose from phone" opens the gallery;
 *   - a record's JSON can be saved into Downloads.
 * Saved enrolments are kept in an SQLite database in the app's own storage.
 */
public class MainActivity extends Activity {

    private static final int PORT = 8765;
    private static final int REQ_CAMERA = 1;
    private static final int REQ_GALLERY = 2;

    private WebView web;
    private ValueCallback<Uri[]> pendingFiles;   // the page waiting for a photo
    private Uri cameraUri;                       // where the camera app writes the photo
    private static volatile boolean readerReady = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#0F1B2D"));
        setContentView(web, new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(true);
        // the screens recognise the app by this (they then hide Reader Training)
        s.setUserAgentString(s.getUserAgentString() + " NIDAPortalApp/1.0");

        web.addJavascriptInterface(new Bridge(), "NIDAApp");
        web.setWebViewClient(new Client());
        web.setWebChromeClient(new Chrome());

        if (readerReady) {
            openScreens(savedInstanceState);
        } else {
            showStarting();
            startReader(savedInstanceState);
        }
    }

    // ------------------------------------------------------------------ the reader (Python)
    private void showStarting() {
        String html = "<html><head><meta name='viewport' content='width=device-width,initial-scale=1'>"
                + "<style>body{margin:0;height:100vh;display:flex;flex-direction:column;align-items:center;"
                + "justify-content:center;background:#0f1b2d;color:#eaf2ff;font-family:sans-serif;text-align:center}"
                + ".s{width:46px;height:46px;border:4px solid rgba(255,255,255,.2);border-top-color:#3ddc97;"
                + "border-radius:50%;animation:r 1s linear infinite;margin-bottom:22px}"
                + "@keyframes r{to{transform:rotate(360deg)}}p{opacity:.7;font-size:14px;margin:6px 24px}</style></head>"
                + "<body><div class='s'></div><h2>NIDA Enrolment</h2><p>Starting the form reader&hellip;</p>"
                + "<p>The first start after installing takes up to a minute.</p></body></html>";
        web.loadDataWithBaseURL(null, html, "text/html", "utf-8", null);
    }

    private void startReader(final Bundle savedInstanceState) {
        new Thread(() -> {
            String error = null;
            try {
                if (!Python.isStarted()) Python.start(new AndroidPlatform(getApplicationContext()));
                PyObject m = Python.getInstance().getModule("nidamobile");
                File data = new File(getFilesDir(), "data");
                int port = m.callAttr("start", data.getAbsolutePath(), PORT).toInt();
                if (!m.callAttr("wait_ready", port, 180).toBoolean()) error = "The reader did not start in time.";
            } catch (Throwable t) {
                error = t.toString();
            }
            final String err = error;
            runOnUiThread(() -> {
                if (err == null) {
                    readerReady = true;
                    openScreens(savedInstanceState);
                } else {
                    new AlertDialog.Builder(MainActivity.this)
                            .setTitle("The form reader could not start")
                            .setMessage(err)
                            .setCancelable(false)
                            .setPositiveButton("Try again", (d, w) -> { showStarting(); startReader(null); })
                            .setNegativeButton("Close", (d, w) -> finish())
                            .show();
                }
            });
        }, "reader-start").start();
    }

    private void openScreens(Bundle savedInstanceState) {
        if (savedInstanceState != null && web.restoreState(savedInstanceState) != null) return;
        web.loadUrl("http://127.0.0.1:" + PORT + "/enrolment/new");
    }

    // ------------------------------------------------------------------ the page
    private class Client extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            Uri u = request.getUrl();
            if ("127.0.0.1".equals(u.getHost())) return false;     // the app's own screens
            try {                                                 // any other link: in the browser
                startActivity(new Intent(Intent.ACTION_VIEW, u));
            } catch (ActivityNotFoundException ignored) {
            }
            return true;
        }
    }

    private class Chrome extends WebChromeClient {
        @Override
        public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
            if (pendingFiles != null) pendingFiles.onReceiveValue(null);
            pendingFiles = callback;
            if (params.isCaptureEnabled()) {
                openCamera();          // the "Take photo" button
            } else {
                openGallery();         // "Choose from phone"
            }
            return true;
        }
    }

    private void openCamera() {
        ContentValues v = new ContentValues();
        v.put(MediaStore.Images.Media.DISPLAY_NAME, "form_" + System.currentTimeMillis() + ".jpg");
        v.put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg");
        v.put(MediaStore.Images.Media.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/NIDA Enrolment");
        cameraUri = getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, v);
        Intent i = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
        i.putExtra(MediaStore.EXTRA_OUTPUT, cameraUri);
        i.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try {
            startActivityForResult(i, REQ_CAMERA);
        } catch (ActivityNotFoundException e) {
            dropCameraFile();
            Toast.makeText(this, "No camera app found", Toast.LENGTH_LONG).show();
            finishChoosing(null);
        }
    }

    private void openGallery() {
        Intent i = new Intent(Intent.ACTION_GET_CONTENT);
        i.setType("image/*");
        i.addCategory(Intent.CATEGORY_OPENABLE);
        try {
            startActivityForResult(Intent.createChooser(i, "Choose the photo of the form"), REQ_GALLERY);
        } catch (ActivityNotFoundException e) {
            finishChoosing(null);
        }
    }

    private void dropCameraFile() {
        if (cameraUri != null) {
            try {
                getContentResolver().delete(cameraUri, null, null);
            } catch (Exception ignored) {
            }
            cameraUri = null;
        }
    }

    private void finishChoosing(Uri[] result) {
        if (pendingFiles != null) pendingFiles.onReceiveValue(result);
        pendingFiles = null;
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_CAMERA) {
            if (resultCode == RESULT_OK && cameraUri != null) {
                finishChoosing(new Uri[]{cameraUri});
                cameraUri = null;
            } else {
                dropCameraFile();
                finishChoosing(null);
            }
        } else if (requestCode == REQ_GALLERY) {
            Uri u = (resultCode == RESULT_OK && data != null) ? data.getData() : null;
            finishChoosing(u != null ? new Uri[]{u} : null);
        }
    }

    // ------------------------------------------------------------------ called from the screens
    private class Bridge {
        /** Not used on the phone (the reader runs here); kept so the screens can call it safely. */
        @JavascriptInterface
        public void changeServer() {
        }

        /** Save a record's JSON into Downloads. */
        @JavascriptInterface
        public void saveFile(String name, String text) {
            runOnUiThread(() -> {
                try {
                    ContentValues v = new ContentValues();
                    v.put(MediaStore.Downloads.DISPLAY_NAME, name);
                    v.put(MediaStore.Downloads.MIME_TYPE, "application/json");
                    v.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS);
                    Uri u = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
                    try (OutputStream out = getContentResolver().openOutputStream(u)) {
                        out.write(text.getBytes(StandardCharsets.UTF_8));
                    }
                    Toast.makeText(MainActivity.this, "Saved in Downloads: " + name, Toast.LENGTH_LONG).show();
                } catch (Exception e) {
                    Toast.makeText(MainActivity.this, "Could not save: " + e.getMessage(), Toast.LENGTH_LONG).show();
                }
            });
        }
    }

    // ------------------------------------------------------------------ back button, rotation
    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        web.saveState(outState);
    }
}
