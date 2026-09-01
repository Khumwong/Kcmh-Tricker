#include "eudaq/Event.hh"
#include "eudaq/FileReader.hh"
#include "eudaq/Logger.hh"
#include "eudaq/StandardEvent.hh"
#include "eudaq/StdEventConverter.hh"

#include <TDirectory.h>
#include <TFile.h>
#include <TF1.h>
#include <TFitResult.h>
#include <TGraphErrors.h>
#include <TH1D.h>
#include <TH2D.h>
#include <TProfile.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <limits>
#include <map>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace {
#ifdef STDEVENTMONITOR_EUDAQ_COMPATIBLE
constexpr bool kEudaqCompatible = true;
#else
constexpr bool kEudaqCompatible = false;
#endif
constexpr int kAlpideNX = 1024;
constexpr int kAlpideNY = 512;
constexpr double kTimestampHz = 80.0e6;
constexpr uint64_t kTimingBinTicks = 800000;  // 10 ms at 80 MHz
constexpr double kPitchXmm = 0.02924;
constexpr double kPitchYmm = 0.02688;
constexpr double kFirstSensorZmm = 112.0;
constexpr double kSensorSpacingMm = 25.0;
constexpr double kCollimatorZmm = -60.0;

struct TimingEntry {
  uint64_t timestamp{};
  uint64_t hits{};
};

struct TimingBin {
  uint64_t hits{};
};

struct PlaneData {
  uint64_t total_hits{};
  std::map<int64_t, uint64_t> hits_by_event;
  std::vector<uint64_t> raw_counts =
      std::vector<uint64_t>(static_cast<size_t>(kAlpideNX) * kAlpideNY, 0);
};

std::string default_output_path(const std::string &input) {
  std::filesystem::path path(input);
  path.replace_extension(".root");
  return path.string();
}

TDirectory *make_directory(TDirectory *parent, const std::string &name) {
  if (auto *existing = parent->GetDirectory(name.c_str())) return existing;
  auto *created = parent->mkdir(name.c_str());
  if (!created) throw std::runtime_error("Could not create ROOT directory: " + name);
  return created;
}

struct CenterFit {
  double center{}, error{}, sigma{};
  bool valid{};
};

CenterFit fit_beam_center(TH1D &projection, const std::string &function_name) {
  CenterFit result;
  if (projection.GetEntries() <= 0 && projection.Integral() <= 0) return result;
  const int peak = projection.GetMaximumBin();
  const double threshold = projection.GetBinContent(peak) * 0.05;
  int low = peak, high = peak;
  while (low > 1 && projection.GetBinContent(low - 1) >= threshold) --low;
  while (high < projection.GetNbinsX() && projection.GetBinContent(high + 1) >= threshold) ++high;
  low = std::max(1, std::min(low, peak - 10));
  high = std::min(projection.GetNbinsX(), std::max(high, peak + 10));
  const double xmin = projection.GetXaxis()->GetBinLowEdge(low);
  const double xmax = projection.GetXaxis()->GetBinUpEdge(high);
  TF1 gaussian(function_name.c_str(), "gaus", xmin, xmax);
  gaussian.SetParameters(projection.GetBinContent(peak), projection.GetBinCenter(peak),
                         std::max(2.0, (xmax - xmin) / 6.0));
  // "N" = do not store the fitted TF1 in the histogram's function list
  // (gaussian is a local; keeping a dangling pointer there crashes teardown).
  const TFitResultPtr fit = projection.Fit(&gaussian, "QS0NR");
  if (static_cast<int>(fit) != 0 || !std::isfinite(gaussian.GetParameter(1)) ||
      !std::isfinite(gaussian.GetParameter(2))) return result;
  result.center = gaussian.GetParameter(1);
  result.error = gaussian.GetParError(1);
  result.sigma = std::abs(gaussian.GetParameter(2));
  result.valid = result.center >= projection.GetXaxis()->GetXmin() &&
                 result.center <= projection.GetXaxis()->GetXmax();
  return result;
}

void usage(const char *program) {
  std::cerr << "Usage: " << program << " RAW_FILE [-o OUTPUT.root]\n";
}
}  // namespace

int main(int argc, char **argv) {
  try {
    EUDAQ_LOG_LEVEL("ERROR");
    EUDAQ_ERR_LEVEL("ERROR");
    // Every ROOT object below is a stack local. Stop ROOT from also taking
    // ownership behind our back, which double-frees them at process teardown:
    //  - histograms auto-register with the open TFile's directory list
    //  - every TF1 auto-registers with gROOT->GetListOfFunctions()
    TH1::AddDirectory(kFALSE);
    TF1::DefaultAddToGlobalList(kFALSE);
    if (argc < 2) {
      usage(argv[0]);
      return 2;
    }

    std::string input;
    std::string output;
    for (int i = 1; i < argc; ++i) {
      const std::string arg(argv[i]);
      if (arg == "-o" || arg == "--output") {
        if (++i >= argc) throw std::runtime_error("Missing value after " + arg);
        output = argv[i];
      } else if (arg == "-h" || arg == "--help") {
        usage(argv[0]);
        return 0;
      } else if (input.empty()) {
        input = arg;
      } else {
        throw std::runtime_error("Unexpected argument: " + arg);
      }
    }
    if (input.empty()) throw std::runtime_error("No raw input file supplied");
    if (output.empty()) output = default_output_path(input);

    auto reader = eudaq::FileReader::Make("native", input);
    if (!reader) throw std::runtime_error("EUDAQ could not open: " + input);

    std::vector<PlaneData> planes(6);
    std::unordered_map<int, uint32_t> first_trigger;
    std::map<int64_t, uint64_t> total_hits_by_event;
    std::map<int64_t, uint64_t> active_mask_by_event;
    // Outer key is normalized TriggerN. This ensures plane timing entries are
    // associated with the same hardware trigger before making time histograms.
    std::map<int64_t, std::unordered_map<int, TimingEntry>> timing_by_trigger;
    std::vector<uint64_t> plane_count_frequency(65, 0);

    uint32_t run_number = 0;
    uint64_t data_events = 0;
    uint64_t bore_events = 0;
    uint64_t eore_events = 0;
    uint64_t reassigned_entries = 0;
    int64_t first_data_event_id = -1;

    while (const auto event = reader->GetNextEvent()) {
      if (event->IsBORE()) {
        ++bore_events;
        continue;
      }
      if (event->IsEORE()) {
        ++eore_events;
        continue;
      }

      if (run_number == 0) run_number = event->GetRunN();
      const int64_t collector_event_id = event->GetEventN();
      if (first_data_event_id < 0) first_data_event_id = collector_event_id;

      std::unordered_map<int, uint32_t> trigger_by_device;
      std::unordered_map<int, uint64_t> timestamp_by_device;
      for (const auto &subevent : event->GetSubEvents()) {
        const int device = static_cast<int>(subevent->GetDeviceN());
        const uint32_t trigger = subevent->GetTriggerN();
        first_trigger.emplace(device, trigger);
        trigger_by_device[device] = trigger;
        timestamp_by_device[device] = subevent->GetTimestampBegin();
      }

      auto standard = eudaq::StandardEvent::MakeShared();
      // Match the Python monitor: malformed subevents can make Convert return
      // false after earlier planes were decoded, so retain any valid planes.
      eudaq::StdEventConverter::Convert(event, standard, nullptr);

      for (size_t i = 0; i < standard->NumPlanes(); ++i) {
        const auto &plane = standard->GetPlane(i);
        const int plane_id = static_cast<int>(plane.ID());
        if (plane_id < 0 || plane_id >= 64)
          throw std::runtime_error("Unsupported plane ID: " + std::to_string(plane_id));
        if (static_cast<size_t>(plane_id) >= planes.size()) planes.resize(plane_id + 1);

        int64_t synchronized_event_id = collector_event_id;
        const auto trigger_it = trigger_by_device.find(plane_id);
        if (trigger_it != trigger_by_device.end()) {
          synchronized_event_id = first_data_event_id +
              static_cast<int64_t>(trigger_it->second) - first_trigger.at(plane_id);
        }
        if (kEudaqCompatible) synchronized_event_id = collector_event_id;
        if (synchronized_event_id != collector_event_id) ++reassigned_entries;

        const uint64_t nhits = plane.HitPixels();
        const auto timestamp_it = timestamp_by_device.find(plane_id);
        if (timestamp_it != timestamp_by_device.end() && timestamp_it->second)
          timing_by_trigger[synchronized_event_id][plane_id] = {timestamp_it->second, nhits};
        auto &data = planes[plane_id];
        data.total_hits += nhits;
        data.hits_by_event[synchronized_event_id] += nhits;
        total_hits_by_event[synchronized_event_id] += nhits;
        active_mask_by_event.try_emplace(synchronized_event_id, 0);
        if (nhits != 0) active_mask_by_event[synchronized_event_id] |= (uint64_t{1} << plane_id);

        const auto &xs = plane.XVector();
        const auto &ys = plane.YVector();
        if (xs.size() != ys.size()) throw std::runtime_error("X/Y vector-size mismatch");
        for (size_t hit = 0; hit < xs.size(); ++hit) {
          const int x = static_cast<int>(xs[hit]);
          const int y = static_cast<int>(ys[hit]);
          if (x >= 0 && x < kAlpideNX && y >= 0 && y < kAlpideNY)
            ++data.raw_counts[static_cast<size_t>(x) * kAlpideNY + y];
        }
      }

      if (standard->NumPlanes() != 0 && standard->NumPlanes() < plane_count_frequency.size())
        ++plane_count_frequency[standard->NumPlanes()];

      ++data_events;
      if (data_events % 10000 == 0)
        std::cout << "Processed " << data_events << " events...\r" << std::flush;
    }
    std::cout << '\n';

    if (total_hits_by_event.empty()) throw std::runtime_error("No converted ALPIDE events found");

    std::vector<uint64_t> first_timestamps(planes.size(), 0);
    std::vector<std::map<uint64_t, TimingBin>> timing_bins(planes.size());
    for (const auto &[trigger_id, entries] : timing_by_trigger) {
      (void)trigger_id;
      for (const auto &[plane_id, entry] : entries) {
        if (plane_id < 0 || static_cast<size_t>(plane_id) >= planes.size() || !entry.timestamp) continue;
        auto &first = first_timestamps[plane_id];
        if (!first) first = entry.timestamp;
        if (entry.timestamp < first) continue;
        auto &bin = timing_bins[plane_id][(entry.timestamp - first) / kTimingBinTicks];
        bin.hits += entry.hits;
      }
    }
    const int64_t min_event_id = total_hits_by_event.begin()->first;
    const int64_t max_event_id = total_hits_by_event.rbegin()->first;
    const int64_t event_bins = max_event_id - min_event_id + 1;
    if (event_bins <= 0 || event_bins > std::numeric_limits<int>::max())
      throw std::runtime_error("Unsupported synchronized Event-ID range");

    TFile root(output.c_str(), "RECREATE");
    if (root.IsZombie()) throw std::runtime_error("Could not create: " + output);

    auto *monitor_dir = make_directory(&root, "EUDAQ Monitor");
    auto *plane_dir = make_directory(monitor_dir, "Planes");
    auto *alpide_dir = make_directory(&root, "ALPIDE");

    TH1D number_of_planes("Number of Planes", "Number of Planes",
                          kEudaqCompatible ? static_cast<int>(planes.size() * 2) : 7,
                          kEudaqCompatible ? 0.0 : -0.5,
                          kEudaqCompatible ? static_cast<double>(planes.size() * 2) : 6.5);
    number_of_planes.GetXaxis()->SetTitle("Active Planes");
    if (kEudaqCompatible) {
      for (size_t nplanes = 0; nplanes < plane_count_frequency.size(); ++nplanes)
        for (uint64_t entry = 0; entry < plane_count_frequency[nplanes]; ++entry)
          number_of_planes.Fill(static_cast<double>(nplanes));
    } else {
      for (const auto &[event_id, mask] : active_mask_by_event)
        number_of_planes.Fill(__builtin_popcountll(mask));
    }

    monitor_dir->cd();
    number_of_planes.Write();

    uint64_t maximum_time_bin = 0;
    for (const auto &sensor_bins : timing_bins)
      if (!sensor_bins.empty()) maximum_time_bin = std::max(maximum_time_bin, sensor_bins.rbegin()->first);
    const int time_bins = static_cast<int>(std::min<uint64_t>(
        maximum_time_bin + 1, static_cast<uint64_t>(std::numeric_limits<int>::max())));
    if (time_bins > 0) {
      TH1D hits_vs_timestamp("Hits vs TimeStamp",
          "TriggerN-synchronized Hits vs TimeStamp;Time from first timestamp [s];Hits / 10 ms",
          time_bins, 0.0, time_bins * 0.01);
      for (const auto &sensor_bins : timing_bins) for (const auto &[index, bin] : sensor_bins) {
        hits_vs_timestamp.AddBinContent(static_cast<int>(index) + 1, static_cast<double>(bin.hits));
      }
      hits_vs_timestamp.Write();
    }
    if (kEudaqCompatible) {
      TProfile hits_vs_event("Hits vs Event", "Hits vs Event", 1000, 0, 20000);
      hits_vs_event.SetCanExtend(TH1::kAllAxes);
      hits_vs_event.GetXaxis()->SetTitle("Event ID");
      for (const auto &[event_id, hits] : total_hits_by_event)
        hits_vs_event.Fill(static_cast<double>(event_id), static_cast<double>(hits));
      hits_vs_event.Write();

      TProfile hits_vs_plane("Hits vs Plane", "Hits vs Plane",
                             static_cast<int>(planes.size()), 0, planes.size());
      hits_vs_plane.GetXaxis()->SetTitle("Plane ID");
      for (size_t plane_id = 0; plane_id < planes.size(); ++plane_id)
        for (const auto &[event_id, hits] : planes[plane_id].hits_by_event)
          hits_vs_plane.Fill(static_cast<double>(plane_id), static_cast<double>(hits));
      hits_vs_plane.Write();
    } else {
      TH1D hits_vs_event("Hits vs Event", "Hits vs Event", static_cast<int>(event_bins),
                         min_event_id - 0.5, max_event_id + 0.5);
      hits_vs_event.GetXaxis()->SetTitle("Event ID");
      for (const auto &[event_id, hits] : total_hits_by_event)
        hits_vs_event.SetBinContent(hits_vs_event.FindBin(event_id), static_cast<double>(hits));
      hits_vs_event.Write();

      TH1D hits_vs_plane("Hits vs Plane", "Hits vs Plane", static_cast<int>(planes.size()),
                         -0.5, static_cast<double>(planes.size()) - 0.5);
      hits_vs_plane.GetXaxis()->SetTitle("Plane ID");
      for (size_t plane_id = 0; plane_id < planes.size(); ++plane_id)
        hits_vs_plane.SetBinContent(static_cast<int>(plane_id) + 1,
                                    static_cast<double>(planes[plane_id].total_hits));
      hits_vs_plane.Write();
    }

    for (size_t plane_id = 0; plane_id < planes.size(); ++plane_id) {
      auto &data = planes[plane_id];
      plane_dir->cd();
      if (time_bins > 0) {
        TH1D sensor_time(("Hits vs TimeStamp Sensor Plane " + std::to_string(plane_id)).c_str(),
            ("TriggerN-synchronized Hits vs TimeStamp Sensor Plane " + std::to_string(plane_id) +
             ";Time from first sensor timestamp [s];Hits / 10 ms").c_str(),
            time_bins, 0.0, time_bins * 0.01);
        for (const auto &[index, bin] : timing_bins[plane_id]) {
          sensor_time.SetBinContent(static_cast<int>(index) + 1, static_cast<double>(bin.hits));
        }
        sensor_time.Write();
      }
      if (kEudaqCompatible) {
        TProfile plane_event(("Hits Sensor Plane " + std::to_string(plane_id)).c_str(),
                             ("Hits vs Event Nr ALPIDE " + std::to_string(plane_id)).c_str(),
                             1000, 0, 20000);
        plane_event.SetCanExtend(TH1::kAllAxes);
        plane_event.GetXaxis()->SetTitle("Event ID");
        for (const auto &[event_id, hits] : data.hits_by_event)
          plane_event.Fill(static_cast<double>(event_id), static_cast<double>(hits));
        plane_event.Write();
      } else {
        TH1D plane_event(("Hits Sensor Plane " + std::to_string(plane_id)).c_str(),
                         ("Hits Sensor Plane " + std::to_string(plane_id)).c_str(),
                         static_cast<int>(event_bins), min_event_id - 0.5, max_event_id + 0.5);
        plane_event.GetXaxis()->SetTitle("Event ID");
        for (const auto &[event_id, hits] : data.hits_by_event)
          plane_event.SetBinContent(plane_event.FindBin(event_id), static_cast<double>(hits));
        plane_event.Write();
      }

      auto *sensor_dir = make_directory(alpide_dir, "Sensor " + std::to_string(plane_id));
      sensor_dir->cd();
      TH2D raw_hitmap("RawHitmap", "RawHitmap", kAlpideNX, -0.5, kAlpideNX - 0.5,
                      kAlpideNY, -0.5, kAlpideNY - 0.5);
      raw_hitmap.GetXaxis()->SetTitle("X Pixel");
      raw_hitmap.GetYaxis()->SetTitle("Y Pixel");
      TH1D x_projection("Hitmap X Projection", "Hitmap X Projection", kAlpideNX,
                        -0.5, kAlpideNX - 0.5);
      TH1D y_projection("Hitmap Y Projection", "Hitmap Y Projection", kAlpideNY,
                        -0.5, kAlpideNY - 0.5);
      for (int x = 0; x < kAlpideNX; ++x) {
        uint64_t xsum = 0;
        for (int y = 0; y < kAlpideNY; ++y) {
          const uint64_t count = data.raw_counts[static_cast<size_t>(x) * kAlpideNY + y];
          if (count != 0) raw_hitmap.SetBinContent(x + 1, y + 1, static_cast<double>(count));
          xsum += count;
        }
        x_projection.SetBinContent(x + 1, static_cast<double>(xsum));
      }
      for (int y = 0; y < kAlpideNY; ++y) {
        uint64_t ysum = 0;
        for (int x = 0; x < kAlpideNX; ++x)
          ysum += data.raw_counts[static_cast<size_t>(x) * kAlpideNY + y];
        y_projection.SetBinContent(y + 1, static_cast<double>(ysum));
      }
      raw_hitmap.Write();
      x_projection.Write();
      y_projection.Write();
    }

    auto *alignment_dir = make_directory(&root, "Alignment");
    alignment_dir->cd();
    TGraphErrors center_x_graph;
    TGraphErrors center_y_graph;
    center_x_graph.SetName("Beam Center X vs Sensor Z");
    center_x_graph.SetTitle("Gaussian Beam Center X vs Sensor Z;Sensor z [mm];Center x [mm]");
    center_y_graph.SetName("Beam Center Y vs Sensor Z");
    center_y_graph.SetTitle("Gaussian Beam Center Y vs Sensor Z;Sensor z [mm];Center y [mm]");
    int valid_x = 0, valid_y = 0;
    for (size_t plane_id = 0; plane_id < planes.size(); ++plane_id) {
      auto *sensor_alignment = make_directory(alignment_dir, "Sensor " + std::to_string(plane_id));
      sensor_alignment->cd();
      TH1D x_fit_hist("X Hit Projection Gaussian Fit",
          ("Sensor " + std::to_string(plane_id) + " X hit projection;X pixel;Hits").c_str(),
          kAlpideNX, -0.5, kAlpideNX - 0.5);
      TH1D y_fit_hist("Y Hit Projection Gaussian Fit",
          ("Sensor " + std::to_string(plane_id) + " Y hit projection;Y pixel;Hits").c_str(),
          kAlpideNY, -0.5, kAlpideNY - 0.5);
      for (int x = 0; x < kAlpideNX; ++x) {
        uint64_t sum = 0;
        for (int y = 0; y < kAlpideNY; ++y)
          sum += planes[plane_id].raw_counts[static_cast<size_t>(x) * kAlpideNY + y];
        x_fit_hist.SetBinContent(x + 1, static_cast<double>(sum));
      }
      for (int y = 0; y < kAlpideNY; ++y) {
        uint64_t sum = 0;
        for (int x = 0; x < kAlpideNX; ++x)
          sum += planes[plane_id].raw_counts[static_cast<size_t>(x) * kAlpideNY + y];
        y_fit_hist.SetBinContent(y + 1, static_cast<double>(sum));
      }
      const auto x_fit = fit_beam_center(x_fit_hist, "gaussian_x_sensor_" + std::to_string(plane_id));
      const auto y_fit = fit_beam_center(y_fit_hist, "gaussian_y_sensor_" + std::to_string(plane_id));
      x_fit_hist.Write();
      y_fit_hist.Write();
      const double z = kFirstSensorZmm + static_cast<double>(plane_id) * kSensorSpacingMm;
      if (x_fit.valid) {
        const double center_mm = (x_fit.center - (kAlpideNX - 1) / 2.0) * kPitchXmm;
        center_x_graph.SetPoint(valid_x, z, center_mm);
        center_x_graph.SetPointError(valid_x, 0.0, x_fit.error * kPitchXmm);
        ++valid_x;
      }
      if (y_fit.valid) {
        const double center_mm = (y_fit.center - (kAlpideNY - 1) / 2.0) * kPitchYmm;
        center_y_graph.SetPoint(valid_y, z, center_mm);
        center_y_graph.SetPointError(valid_y, 0.0, y_fit.error * kPitchYmm);
        ++valid_y;
      }
    }
    alignment_dir->cd();
    TF1 x_line("Beam X Linear Fit", "pol1", kFirstSensorZmm,
               kFirstSensorZmm + std::max(1.0, (static_cast<double>(planes.size()) - 1.0) * kSensorSpacingMm));
    TF1 y_line("Beam Y Linear Fit", "pol1", kFirstSensorZmm,
               kFirstSensorZmm + std::max(1.0, (static_cast<double>(planes.size()) - 1.0) * kSensorSpacingMm));
    if (valid_x >= 2) center_x_graph.Fit(&x_line, "QS0NR");
    if (valid_y >= 2) center_y_graph.Fit(&y_line, "QS0NR");
    center_x_graph.Write();
    center_y_graph.Write();
    const double slope_x = valid_x >= 2 ? x_line.GetParameter(1) : std::numeric_limits<double>::quiet_NaN();
    const double slope_y = valid_y >= 2 ? y_line.GetParameter(1) : std::numeric_limits<double>::quiet_NaN();
    const double offset_x = valid_x >= 2 ? x_line.Eval(kCollimatorZmm) : std::numeric_limits<double>::quiet_NaN();
    const double offset_y = valid_y >= 2 ? y_line.Eval(kCollimatorZmm) : std::numeric_limits<double>::quiet_NaN();
    const double angle_x = std::atan(slope_x) * 180.0 / M_PI;
    const double angle_y = std::atan(slope_y) * 180.0 / M_PI;
    const double transverse_slope = std::hypot(slope_x, slope_y);
    const double total_angle = std::atan(transverse_slope) * 180.0 / M_PI;
    const double slope_x_error = valid_x >= 2 ? x_line.GetParError(1) : 0.0;
    const double slope_y_error = valid_y >= 2 ? y_line.GetParError(1) : 0.0;
    const double offset_x_error = valid_x >= 2 ? std::hypot(x_line.GetParError(0), kCollimatorZmm * slope_x_error) : 0.0;
    const double offset_y_error = valid_y >= 2 ? std::hypot(y_line.GetParError(0), kCollimatorZmm * slope_y_error) : 0.0;
    const double degree = 180.0 / M_PI;
    const double angle_x_error = slope_x_error / (1.0 + slope_x * slope_x) * degree;
    const double angle_y_error = slope_y_error / (1.0 + slope_y * slope_y) * degree;
    double total_angle_error = 0.0;
    if (transverse_slope > 0.0)
      total_angle_error = std::hypot(slope_x * slope_x_error, slope_y * slope_y_error) /
                          (transverse_slope * (1.0 + transverse_slope * transverse_slope)) * degree;

    TH1D beam_offset("Beam Offset at Collimator Exit",
        "Beam Offset at Collimator Exit (z_{0}=-60 mm);Coordinate;Offset [mm]", 2, 0.5, 2.5);
    beam_offset.GetXaxis()->SetBinLabel(1, "x_{0}");
    beam_offset.GetXaxis()->SetBinLabel(2, "y_{0}");
    beam_offset.SetBinContent(1, offset_x);
    beam_offset.SetBinContent(2, offset_y);
    beam_offset.SetBinError(1, offset_x_error);
    beam_offset.SetBinError(2, offset_y_error);
    beam_offset.SetMarkerStyle(20);
    beam_offset.SetStats(false);
    beam_offset.Write();

    TH1D beam_angles("Beam Angles",
        "Beam Direction Angles;Projection;Angle [deg]", 3, 0.5, 3.5);
    beam_angles.GetXaxis()->SetBinLabel(1, "XZ");
    beam_angles.GetXaxis()->SetBinLabel(2, "YZ");
    beam_angles.GetXaxis()->SetBinLabel(3, "to Z axis");
    beam_angles.SetBinContent(1, angle_x);
    beam_angles.SetBinContent(2, angle_y);
    beam_angles.SetBinContent(3, total_angle);
    beam_angles.SetBinError(1, angle_x_error);
    beam_angles.SetBinError(2, angle_y_error);
    beam_angles.SetBinError(3, total_angle_error);
    beam_angles.SetMarkerStyle(20);
    beam_angles.SetStats(false);
    beam_angles.Write();

    TH1D alignment_geometry("Alignment Geometry",
        "Alignment Geometry;Parameter;Distance [mm]", 5, 0.5, 5.5);
    alignment_geometry.GetXaxis()->SetBinLabel(1, "Collimator z_{0}");
    alignment_geometry.GetXaxis()->SetBinLabel(2, "First sensor z");
    alignment_geometry.GetXaxis()->SetBinLabel(3, "Sensor spacing");
    alignment_geometry.GetXaxis()->SetBinLabel(4, "Pixel pitch X");
    alignment_geometry.GetXaxis()->SetBinLabel(5, "Pixel pitch Y");
    alignment_geometry.SetBinContent(1, kCollimatorZmm);
    alignment_geometry.SetBinContent(2, kFirstSensorZmm);
    alignment_geometry.SetBinContent(3, kSensorSpacingMm);
    alignment_geometry.SetBinContent(4, kPitchXmm);
    alignment_geometry.SetBinContent(5, kPitchYmm);
    alignment_geometry.SetMarkerStyle(20);
    alignment_geometry.SetStats(false);
    alignment_geometry.Write();

    root.Close();
    std::cout << "Run number         : " << run_number << '\n'
              << "Data events        : " << data_events << '\n'
              << "BORE/EORE skipped  : " << bore_events << '/' << eore_events << '\n'
              << "Event ID range     : " << min_event_id << " -> " << max_event_id << '\n'
              << "Event assignment   : "
              << (kEudaqCompatible ? "collector EventN (EUDAQ compatible)\n"
                                   : "trigger synchronized\n")
              << "Plane entries moved: " << reassigned_entries << '\n'
              << "ROOT file written  : " << output << '\n';
    for (size_t plane_id = 0; plane_id < planes.size(); ++plane_id)
      std::cout << "Plane " << plane_id << " total hits: " << planes[plane_id].total_hits << '\n';

    // The ROOT file is closed and flushed above; all work is done. Skip global
    // destructors: on hosts with two ROOT installs visible (e.g. EUDAQ built
    // against a different ROOT than root-config points at) their duplicated
    // static teardown corrupts the heap and aborts with a non-zero exit long
    // after the output is safely on disk.
    std::cout.flush();
    std::fflush(nullptr);
    std::_Exit(0);
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "ERROR: " << error.what() << '\n';
    std::cerr.flush();
    std::fflush(nullptr);
    std::_Exit(1);
    return 1;
  }
}
